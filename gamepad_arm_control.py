#!/usr/bin/env python3
"""DOFBOT USB gamepad step/hold control. Default is a no-hardware preview."""
import argparse
import glob
import json
import math
import os
import struct
import time

AXES = (0, 1, 5, 2)
NAMES = {1: '底座', 2: '大臂', 3: '小臂', 4: '腕部', 5: '末端旋转', 6: '夹爪'}
BUTTON_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gamepad_buttons.json')
POLL_SECONDS = 0.01
COMMAND_MAX_AGE = 0.5
HOLD_PERIOD = 0.1
HOLD_DURATION_MS = 150
HOLD_MAX_LEAD = 4
STALL_SECONDS = 0.8
INITIAL_RETRY_SECONDS = 3.0
VERSION = '2026-09-24-comm3'
BUS_GAP = 0.05
REPLY_DELAY = 0.05
BUS_COOLDOWN = 5.0


class MotionPaused(RuntimeError):
    """Stop this gesture while keeping the controller available for fresh input."""


class MotionSession:
    def __init__(self):
        self.blocked = {}

    def check(self, joint, direction):
        if (joint, direction) in self.blocked:
            description = '夹爪继续闭合' if joint == 6 and direction > 0 else f'{joint}号该方向'
            raise MotionPaused(f'{description}已锁住，本次忽略；反向实际移动至少 2°后解除，可操作其它关节。')

    def block(self, joint, direction, angle):
        self.blocked[joint, direction] = angle

    def observe(self, joint, direction, angle):
        opposite = (joint, -direction)
        if opposite in self.blocked and direction * (angle - self.blocked[opposite]) >= 2:
            del self.blocked[opposite]
            print(f'{joint}号已确认反向移动，解除先前方向锁定。', flush=True)


def neutral_input(state):
    return (state is not None and not any(state[3:])
            and all(abs(state[0][axis] - 128) <= 25 for axis in AXES))


def action_from_state(axes, l1, r1, open_key=False, close_key=False):
    active = [axis for axis in AXES if abs(axes[axis] - 128) > 25]
    if len(active) + int(open_key) + int(close_key) != 1:
        return None
    if open_key or close_key:
        return 6, -1 if open_key else 1
    axis = active[0]
    mapping = {0: 1, 1: 4 if l1 else 2, 2: 3}
    if r1:
        mapping[5] = 5
    joint = mapping.get(axis)
    return (joint, 1 if axes[axis] > 128 else -1) if joint else None


def same_action(original, latest, action):
    # A recognized tap commits one step: ordinary release is not cancellation.
    # New modifiers, a different direction, or conflicting inputs still cancel.
    if latest is None or any(new and not old for old, new in zip(original[1:3], latest[1:3])):
        return False
    if neutral_input(latest):
        return True
    return latest[1:3] == original[1:3] and action_from_state(*latest) == action


class Gate:
    """One action per neutral-to-input gesture; modifiers must be set at neutral."""
    def __init__(self):
        self.ready = False
        self.mode = (False, False)

    def update(self, axes, l1, r1, open_key=False, close_key=False):
        active = [axis for axis in AXES if abs(axes[axis] - 128) > 25]
        if not active and not open_key and not close_key:
            self.ready = True
            self.mode = (l1, r1)
            return None
        ready = self.ready
        self.ready = False
        if not ready or (l1, r1) != self.mode:
            return None
        return action_from_state(axes, l1, r1, open_key, close_key)


def find_pad():
    found = []
    for path in glob.glob('/sys/class/input/event*/device/id/vendor'):
        with open(path) as f:
            vendor = f.read().strip()
        with open(os.path.join(os.path.dirname(path), 'product')) as f:
            product = f.read().strip()
        if (vendor, product) == ('0810', '0001'):
            found.append('/dev/input/' + path.split('/')[-4])
    if len(found) != 1:
        raise RuntimeError('需要连接唯一一个 0810:0001 USB Gamepad。')
    return found[0]


def ioctl_read(fd, number, size):
    import fcntl
    data = bytearray(size)
    # Linux asm-generic ioctl layout, used by aarch64 and x86_64.
    request = (2 << 30) | (size << 16) | (ord('E') << 8) | number
    fcntl.ioctl(fd, request, data, True)
    return data


def pressed_keys(fd):
    bits = ioctl_read(fd, 0x18, 96)  # EVIOCGKEY
    return {k for k in range(288, 300) if bits[k // 8] & (1 << (k % 8))}


def buttons(fd, key_codes):
    pressed = pressed_keys(fd)
    return tuple(k in pressed for k in (292, 293, *key_codes))


def snapshot(fd, key_codes):
    before = buttons(fd, key_codes)
    axes = {}
    for code in AXES:
        value, low, high, _, _, _ = struct.unpack('=6i', ioctl_read(fd, 0x40 + code, 24))
        if (low, high) != (0, 255) or not 0 <= value <= 255:
            raise RuntimeError('手柄轴范围不匹配，停止。')
        axes[code] = value
    after = buttons(fd, key_codes)
    if before != after:
        return None
    return (axes, *after)


def valid_key_codes(codes):
    return (isinstance(codes, list) and len(codes) == 2
            and all(type(k) is int and 288 <= k < 300 and k not in (292, 293) for k in codes)
            and codes[0] != codes[1])


def configure_buttons(fd, path=BUTTON_CONFIG, force=False):
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                codes = json.load(f)
        except (ValueError, UnicodeError):
            raise RuntimeError('数字键配置无法读取，请使用 --configure-buttons 重新识别。')
        if not valid_key_codes(codes):
            raise RuntimeError('数字键配置无效，请使用 --configure-buttons 重新识别。')
        return codes
    print('重新识别实体数字键，期间不访问机械臂。保持 ANALOG 模式，摇杆回中。', flush=True)
    print('请看手柄上印刷的数字，不按屏幕事件编号猜键；每个键需按下、松开，再按一次。', flush=True)
    codes = []
    for label in ('1（打开夹爪）', '3（关闭夹爪）'):
        print(f'请松开所有按键，然后单独按实体数字 {label} 键。', flush=True)
        released = False
        candidate = None
        while True:
            pressed = pressed_keys(fd)
            if not pressed:
                released = True
            elif released:
                if len(pressed) == 1:
                    code = next(iter(pressed))
                    if code not in (292, 293) and code not in codes:
                        if candidate is None:
                            candidate = code
                            print(f'第一次收到事件码 {code}。请松开，再按同一个实体数字 {label} 键确认。', flush=True)
                        elif code == candidate:
                            codes.append(code)
                            print(f'已确认数字 {label}：事件码 {code}', flush=True)
                            break
                        else:
                            candidate = None
                            print('两次按键不同，请松开，重新按指定实体数字键两次。', flush=True)
                    else:
                        print('请只按指定数字键，不要按 L1/R1 或前一个已保存的键。', flush=True)
                else:
                    print('检测到多个按键，请松开后只按指定数字键。', flush=True)
                released = False
            time.sleep(0.05)
    print('请松开所有按键。', flush=True)
    while pressed_keys(fd):
        time.sleep(0.05)
    temporary = path + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as f:
        json.dump(codes, f)
        f.write('\n')
    os.replace(temporary, path)
    print('数字键配置已保存：', path, flush=True)
    return codes


def check_other_controllers():
    # This catches common project entry points, not every possible I2C client.
    for path in glob.glob('/proc/[0-9]*/cmdline'):
        if path.split('/')[2] == str(os.getpid()):
            continue
        try:
            with open(path, 'rb') as f:
                words = f.read().split(b'\0')
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if any(os.path.basename(w) in (b'block_cls', b'color_stacking') for w in words):
            raise RuntimeError('检测到分拣/堆叠程序，请先 Ctrl+C 停止该程序。')


class FeedbackUnavailable(RuntimeError):
    """The controller returned zero raw counts, not a valid zero-degree angle."""


class PacedArm:
    """One shared transaction schedule and circuit breaker for all six servos."""
    def __init__(self, arm, motion_rest=BUS_GAP):
        self.bus, self.addr = arm.bus, arm.addr
        self.motion_rest = motion_rest
        self.available_at = 0.0
        self.retry_at = 0.0
        self.failed_joint = None

    def fail(self, joint, reason):
        self.failed_joint = joint
        self.retry_at = time.monotonic() + BUS_COOLDOWN
        raise MotionPaused(f'{joint}号通信暂不可用（{reason}）；全部关节暂停读写5秒，'
                           '回中并松开数字键后仅检查反馈，不自动恢复运动。')

    def read_raw(self, joint):
        if time.monotonic() < self.retry_at:
            raise MotionPaused('通信静默等待中，本次不访问机械臂。')
        delay = self.available_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        reg = 0x30 + joint
        try:
            self.bus.write_byte_data(self.addr, reg, 0)
            time.sleep(REPLY_DELAY)
            raw = self.bus.read_word_data(self.addr, reg)
        except OSError as exc:
            self.fail(joint, str(exc))
        self.available_at = time.monotonic() + BUS_GAP
        pos = ((raw >> 8) & 255) | ((raw << 8) & 0xff00)
        if pos == 0:
            self.fail(joint, '原始反馈为0')
        return pos

    def Arm_serial_servo_write(self, joint, target, duration):
        # Use the documented Arm_Lib packet, but propagate I2C errors rather
        # than letting Arm_Lib print and swallow them. Never retry a write.
        if self.failed_joint is not None:
            raise MotionPaused('通信尚未恢复，本次不发送运动。')
        if time.monotonic() + 1e-6 < self.available_at:
            raise MotionPaused('通信间隔尚未满足，本次不发送运动，请回中后重试。')
        maximum = 270 if joint == 5 else 180
        if joint not in range(1, 7) or not 0 <= target <= maximum or not 0 < duration <= 65535:
            raise MotionPaused('运动参数无效，本次不发送。')
        angle = 180 - target if joint in (2, 3, 4) else target
        low, high = (380, 3700) if joint == 5 else (900, 3100)
        pos = int((high - low) * angle / maximum + low)
        try:
            self.bus.write_i2c_block_data(self.addr, 0x10 + joint,
                                        [pos >> 8, pos & 255, duration >> 8, duration & 255])
        except OSError as exc:
            self.fail(joint, str(exc))
        self.available_at = time.monotonic() + duration / 1000 + self.motion_rest

    def recover_if_neutral(self, state):
        if not neutral_input(state) or time.monotonic() < self.retry_at:
            return
        joint = self.failed_joint
        try:
            angle = stable_angle(self, joint)
        except MotionPaused as exc:
            print(exc, flush=True)
            return
        except (RuntimeError, OSError) as exc:
            try:
                self.fail(joint, str(exc))
            except MotionPaused as paused:
                print(paused, flush=True)
            return
        self.failed_joint = None
        print(f'通信复查成功：{joint}号反馈 {angle}°；未发送运动。请回中后重新操作。', flush=True)


def angle_once(arm, joint):
    # Production access uses the shared schedule; bare adapters support offline checks.
    if isinstance(arm, PacedArm):
        pos = arm.read_raw(joint)
    else:
        reg = 0x30 + joint
        arm.bus.write_byte_data(arm.addr, reg, 0)
        time.sleep(0.02)
        raw = arm.bus.read_word_data(arm.addr, reg)
        pos = ((raw >> 8) & 255) | ((raw << 8) & 0xff00)
    low, high, maximum = (380, 3700, 270) if joint == 5 else (900, 3100, 180)
    # Match Arm_Lib: validate the converted whole-degree reading, not raw counts.
    # E.g. pos=3104 converts to int(180.327)=180; inverted joint 3 reads 0.
    angle = int(maximum * (pos - low) / (high - low))
    if pos == 0:
        raise FeedbackUnavailable(f'{joint}号本次反馈原始值为 0')
    if not 0 <= angle <= maximum:
        if isinstance(arm, PacedArm):
            arm.fail(joint, f'无效原始反馈{pos}')
        raise RuntimeError(f'{joint}号反馈无效：{pos}，没有继续发指令。')
    return 180 - angle if joint in (2, 3, 4) else angle


def stable_angle(arm, joint):
    previous = None
    # Only retry feedback requests; never repeat a servo motion command.
    for attempt in range(4):
        try:
            angle = angle_once(arm, joint)
        except FeedbackUnavailable:
            previous = None
            print(f'{joint}号反馈原始值为 0（第 {attempt + 1}/4 次读取），未当作角度使用。', flush=True)
            if attempt < 3:
                time.sleep(0.08)
            continue
        if previous is not None:
            if abs(previous - angle) > 2:
                raise RuntimeError(f'{joint}号角度不稳定：{previous}, {angle}，停止。')
            return angle
        previous = angle
        if attempt < 3:
            time.sleep(0.05)
    raise RuntimeError(f'{joint}号在 4 次读取内未取得连续两次有效稳定反馈，停止；未重发运动指令。')


class LimitReached(RuntimeError):
    """A valid reading whose next requested step would exceed the session limits."""


def target_angle(current, direction, initial, maximum, step=2, span=10):
    target = current + direction * step
    low, high = max(0, initial - span), min(maximum, initial + span)
    if not low <= current <= high:
        raise RuntimeError(f'当前反馈 {current}° 已超出本次范围 {low}°–{high}°，停止。')
    if not low <= target <= high:
        raise LimitReached(f'目标 {target}° 超出本次范围 {low}°–{high}°，本次不动作。'
                           '松开数字键并让摇杆回中后，可反向操作或控制其它关节。')
    return target


def movement_duration_ms(step, speed):
    return max(800, (step * 1000 + speed - 1) // speed)


def still_held(original, latest, action):
    return (latest is not None and latest[1:3] == original[1:3]
            and action_from_state(*latest) == action)


def input_strength(state, joint):
    if joint == 6:
        return 1.0
    axis = {1: 0, 2: 1, 3: 2, 4: 1, 5: 5}[joint]
    return min(1.0, max(0.0, (abs(state[0][axis] - 128) - 25) / 102))


def advance_hold(position, direction, strength, speed, elapsed, low, high):
    # Fractional angles accumulate, but delayed iterations never catch up in a burst.
    position = min(high, max(low, position + direction * strength * speed * min(elapsed, 0.2)))
    target = math.floor(position + 1e-9) if direction > 0 else math.ceil(position - 1e-9)
    return position, target


def hold_feedback(arm, joint, stable=True):
    try:
        return stable_angle(arm, joint) if stable else angle_once(arm, joint)
    except MotionPaused:
        raise
    except FeedbackUnavailable:
        if not stable:
            raise
        raise MotionPaused(f'{joint}号反馈暂不可用，本次不动作。')
    except (RuntimeError, OSError) as exc:
        raise MotionPaused(f'{joint}号反馈检查未通过：{exc}；本次停止，回中后可重新检查。') from exc


def try_initialize_joint(arm, joint, initial):
    """Latch the first valid baseline only; never infer one or send a motion."""
    if joint in initial:
        return True
    try:
        angle = hold_feedback(arm, joint)
    except MotionPaused as exc:
        print(f'{joint}号尚未就绪，已禁用该关节运动，等待重新读取：{exc}', flush=True)
        return False
    initial[joint] = angle
    print(f'{joint}号初始角度已确认：{angle}°。本次仅初始化，不发送运动。', flush=True)
    return True


def hold_write(arm, joint, target):
    try:
        arm.Arm_serial_servo_write(joint, target, HOLD_DURATION_MS)
    except OSError as exc:
        raise MotionPaused(f'{joint}号发送失败，本次停止，不自动重发：{exc}') from exc


def block_direction(arm, joint, direction, actual, session):
    # Keep torque on, but remove the unachieved target that was asking for more travel.
    session.block(joint, direction, actual)
    reason = '夹爪疑似夹紧或受阻' if joint == 6 and direction > 0 else f'{joint}号疑似受阻'
    print(f'{reason}；锁住本方向，保持已确认角度 {actual}°，仍可反向及控制其它关节。', flush=True)
    time.sleep(0.05)
    hold_write(arm, joint, actual)


def finish_hold(arm, joint, target, low, high, session, direction):
    # Let the last short segment finish before validating or accepting another gesture.
    time.sleep(HOLD_DURATION_MS / 1000 + 0.05)
    actual = hold_feedback(arm, joint)
    if not low <= actual <= high:
        raise MotionPaused(f'{joint}号反馈 {actual}° 超出范围，本次停止。')
    session.observe(joint, direction, actual)
    if direction * (target - actual) > 3:
        block_direction(arm, joint, direction, actual, session)
    elif abs(actual - target) > 3:
        raise MotionPaused(f'{joint}号停止后的反馈 {actual}° 偏离目标 {target}°，本次停止。')
    print(f'{joint}号停止后反馈：{actual}°。', flush=True)


def execute_hold(arm, action, state, initial, args, read_state, session=None):
    joint, direction = action
    if session is None:
        session = MotionSession()
    session.check(joint, direction)
    accepted_at = time.monotonic()
    check_other_controllers()
    current = hold_feedback(arm, joint)
    low = max(0, initial[joint] - args.span)
    high = min(270 if joint == 5 else 180, initial[joint] + args.span)
    if not low <= current <= high:
        raise MotionPaused(f'{joint}号当前反馈 {current}° 超出本次范围 {low}°–{high}°，本次不动作。')
    session.observe(joint, direction, current)
    latest = read_state()
    if time.monotonic() - accepted_at > COMMAND_MAX_AGE or not still_held(state, latest, action):
        print('输入已松开/改变或检查超时，没有开始连续移动。', flush=True)
        return
    position = float(current)
    last_target = current
    last_tick = time.monotonic()
    next_tick = last_tick + HOLD_PERIOD
    last_report = last_tick
    last_process_check = last_tick
    progress_angle = current
    progress_at = last_tick
    waiting_reported = False
    print(f'连续控制：{joint}号{NAMES[joint]}，松手停止续发，范围 {low}°–{high}°。', flush=True)
    while True:
        latest = read_state()
        if not still_held(state, latest, action):
            print('已停止续发；最后一段短动作可能尚在完成。回中并松开数字键后可继续。', flush=True)
            if last_target != current:
                finish_hold(arm, joint, last_target, low, high, session, direction)
            return
        now = time.monotonic()
        # The deliberate bus rest is not a stalled input loop. Inputs are
        # still sampled every 10ms while waiting for the scheduled query.
        if now - next_tick > COMMAND_MAX_AGE:
            print('控制循环延迟，已停止续发；回中后重新操作。', flush=True)
            if last_target != current:
                finish_hold(arm, joint, last_target, low, high, session, direction)
            return
        if now < next_tick:
            time.sleep(min(POLL_SECONDS, next_tick - now))
            continue
        if now - last_process_check >= 1:
            check_other_controllers()
            last_process_check = now
        try:
            actual = hold_feedback(arm, joint, stable=False)
        except FeedbackUnavailable:
            # Pause motion immediately; recovery only reads, and requires a new gesture.
            print('反馈暂缺，已停止连续指令，仅重读反馈；回中后再操作。', flush=True)
            time.sleep(HOLD_DURATION_MS / 1000)
            finish_hold(arm, joint, last_target, low, high, session, direction)
            return
        time.sleep(0.05)  # Keep the known-working feedback-to-write bus interval.
        latest = read_state()
        now = time.monotonic()
        if now - next_tick > COMMAND_MAX_AGE or not still_held(state, latest, action):
            reason = ('反馈检查超时' if now - next_tick > COMMAND_MAX_AGE
                      else '输入已松开、改变或出现冲突')
            print(f'{reason}，已停止续发。', flush=True)
            if last_target != current:
                finish_hold(arm, joint, last_target, low, high, session, direction)
            return
        if not low <= actual <= high:
            raise MotionPaused(f'{joint}号反馈 {actual}° 超出本次范围，本次停止。')
        session.observe(joint, direction, actual)
        if abs(last_target - actual) > HOLD_MAX_LEAD + 3:
            raise MotionPaused(f'{joint}号反馈明显偏离最近目标，本次停止，回中后重新检查。')
        if direction * (actual - progress_angle) >= 1:
            progress_angle = actual
            progress_at = now
        lag = direction * (last_target - actual)
        if lag < 2:
            progress_at = now
        elif now - progress_at >= STALL_SECONDS:
            # Verify a settled reading before treating a lack of progress as obstruction.
            time.sleep(HOLD_DURATION_MS / 1000 + 0.05)
            settled = hold_feedback(arm, joint)
            if not low <= settled <= high:
                raise MotionPaused(f'{joint}号复查反馈超出范围，本次停止。')
            if direction * (last_target - settled) >= 2:
                block_direction(arm, joint, direction, settled, session)
            else:
                print('反馈已跟上；本次暂停结束，回中后可以继续。', flush=True)
            return
        position, target = advance_hold(position, direction, input_strength(latest, joint),
                                        args.speed, now - last_tick, low, high)
        requested = target
        # Bound the lead by measured position without moving backwards or accumulating debt.
        if direction > 0:
            target = max(last_target, min(target, actual + HOLD_MAX_LEAD))
        else:
            target = min(last_target, max(target, actual - HOLD_MAX_LEAD))
        if requested != target:
            position = float(target)
            if not waiting_reported:
                print('目标已领先反馈，正在减速等待，不再累积更远的目标。', flush=True)
                waiting_reported = True
        else:
            waiting_reported = False
        if target != last_target:
            hold_write(arm, joint, target)
            last_target = target
        last_tick = now
        next_tick = max(now + max(HOLD_PERIOD, getattr(arm, 'motion_rest', BUS_GAP)),
                        getattr(arm, 'available_at', 0.0))
        if now - last_report >= 1:
            print(f'{joint}号反馈 {actual}°，当前目标 {last_target}°。', flush=True)
            last_report = now
        if position == (high if direction > 0 else low):
            print(f'{joint}号已发送边界目标 {target}°，停止续发；回中后可反向操作。', flush=True)
            if last_target != current:
                finish_hold(arm, joint, last_target, low, high, session, direction)
            return


def execute_step(arm, action, state, initial, args, read_state):
    """Consume one recognized gesture without queuing or requiring a long hold."""
    accepted_at = time.monotonic()
    joint, direction = action
    label = ('张开' if direction < 0 else '闭合') if joint == 6 else ''
    print(f'收到：{joint}号{NAMES[joint]} {label} {direction * args.step:+d}°，正在检查角度。', flush=True)
    check_other_controllers()
    current = stable_angle(arm, joint)
    target = target_angle(current, direction, initial[joint],
                          270 if joint == 5 else 180, args.step, args.span)
    time.sleep(0.05)  # Leave a short bus gap between feedback and the servo write.
    latest = read_state()  # Also checks that the gamepad is still connected.
    if time.monotonic() - accepted_at > COMMAND_MAX_AGE:
        print('本次检查耗时过长，已丢弃这一步，请重新操作。', flush=True)
        return
    if not same_action(state, latest, action):
        print('检测到新方向、组合键变化或输入冲突，取消这一步。', flush=True)
        return
    duration_ms = movement_duration_ms(args.step, args.speed)
    print(f'{joint}号{NAMES[joint]}：{current}° → {target}°；执行中，期间的其它操作不排队。', flush=True)
    arm.Arm_serial_servo_write(joint, target, duration_ms)
    time.sleep(duration_ms / 1000 + 0.4)
    actual = stable_angle(arm, joint)
    print('反馈角度：', actual, flush=True)
    if abs(actual - target) > 2:
        raise RuntimeError('反馈未接近目标，停止发送；请检查实际动作。')


def run(args):
    import fcntl
    print(f'控制脚本版本：{VERSION}（运动完成后查询；通信失败全局静默5秒）', flush=True)
    duration_ms = movement_duration_ms(args.step, args.speed)
    check_other_controllers()
    path = find_pad()
    with open('/tmp/dofbot_gamepad.lock', 'a') as lock, open(path, 'rb', buffering=0) as pad:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        arm = None
        initial = {}
        try:
            key_codes = configure_buttons(pad.fileno(), force=args.configure_buttons)
            if args.configure_buttons:
                return
            print(f'数字键配置：1={key_codes[0]}（张开），3={key_codes[1]}（闭合）。', flush=True)
            snapshot(pad.fileno(), key_codes)
            if args.move:
                from Arm_Lib import Arm_Device
                arm = PacedArm(Arm_Device(), args.hold_rest_ms / 1000
                               if args.mode == 'hold' else BUS_GAP)
                for joint in args.joints:
                    if args.mode == 'hold':
                        try_initialize_joint(arm, joint, initial)
                    else:
                        initial[joint] = stable_angle(arm, joint)
                    if arm.failed_joint is not None:
                        break
                print('实物模式：起始角度', initial, flush=True)
                pending = [j for j in args.joints if j not in initial]
                if pending:
                    print(f'等待初始反馈的关节：{pending}。程序继续运行，回中时每3秒轮流重读一个；这些关节暂不动作。', flush=True)
                if args.mode == 'hold':
                    print(f'按住连续模式：最高 {args.speed}°/秒，范围起点 ±{args.span}°；--step 不参与连续控制。', flush=True)
                    print(f'每段运动完成后静默 {args.hold_rest_ms}ms 再查询；等待期间仍检测松手。'
                          '不补偿等待期间的行程，实际平均速度会降低。', flush=True)
                else:
                    print(f'每次 {args.step}°，{duration_ms}ms；每个关节限起点 ±{args.span}°，无自动复位或扭矩切换。', flush=True)
            else:
                print('预览模式：不访问机械臂。', flush=True)
            print('设备：', path, '允许关节：', args.joints, flush=True)
            print('左摇杆左右=底座，上下=大臂；右摇杆上下=小臂，无需 L1。', flush=True)
            print('L1+左摇杆上下=腕部；R1+右摇杆左右=末端旋转；数字1=张开，数字3=闭合。', flush=True)
            if args.mode == 'hold':
                print('按住才续发；摇杆推幅控制速度，数字1/3按住控制夹爪。一次控制一个关节，换方向/组合键前回中。', flush=True)
                print('松手或断开后不再下发目标，最后一段150ms短动作仍可能完成；不自动复位或释放扭矩。', flush=True)
                print('反馈滞后会减速等待；疑似受阻会锁住该方向，反向实际移动2°后解锁。反馈异常只取消本次动作。', flush=True)
            else:
                print('每推/按一次只移动一步；再次动作前摇杆回中、数字键松开。组合键请先按 L1/R1 再推杆。', flush=True)
                print('短按/短推被识别后松手仍执行一步；等待“就绪”再操作，不在运动期间连续按键。', flush=True)
            gate = Gate()
            session = MotionSession()
            ready_announced = False
            next_initial_retry = time.monotonic() + INITIAL_RETRY_SECONDS
            retry_index = 0
            while True:
                state = snapshot(pad.fileno(), key_codes)
                if state is None:
                    gate = Gate()
                    ready_announced = False
                    time.sleep(POLL_SECONDS)
                    continue
                if arm is not None and arm.failed_joint is not None:
                    arm.recover_if_neutral(state)
                    gate = Gate()
                    ready_announced = False
                    time.sleep(POLL_SECONDS)
                    continue
                pending = [j for j in args.joints if j not in initial] if arm is not None else []
                if (args.mode == 'hold' and pending and neutral_input(state)
                        and time.monotonic() >= next_initial_retry):
                    joint = pending[retry_index % len(pending)]
                    retry_index += 1
                    try_initialize_joint(arm, joint, initial)
                    next_initial_retry = time.monotonic() + INITIAL_RETRY_SECONDS
                    # Input during feedback reads is never queued for execution.
                    gate = Gate()
                    ready_announced = False
                    continue
                action = gate.update(*state)
                if gate.ready and not ready_announced:
                    if pending:
                        print(f'输入就绪：可控关节 {sorted(initial)}；待反馈关节 {pending} 暂不动作。', flush=True)
                    else:
                        print('就绪：可以推杆或按数字 1/3。', flush=True)
                    ready_announced = True
                elif not gate.ready:
                    if ready_announced and action is None:
                        print('输入未形成单一有效动作；请回中并松开数字键，再按目标键或推杆。', flush=True)
                    ready_announced = False
                if action:
                    joint, direction = action
                    if joint not in args.joints:
                        print(f'{joint}号未启用，本次不动作。', flush=True)
                    elif arm is None:
                        label = ('张开' if direction < 0 else '闭合') if joint == 6 else ''
                        if args.mode == 'hold':
                            print(f'预览映射：{joint}号{NAMES[joint]} {label} 方向{direction:+d}；连续速度随推幅改变。', flush=True)
                        else:
                            print(f'预览：{joint}号{NAMES[joint]} {label} {direction * args.step:+d}°', flush=True)
                    elif joint not in initial:
                        try_initialize_joint(arm, joint, initial)
                        next_initial_retry = time.monotonic() + INITIAL_RETRY_SECONDS
                        gate = Gate()
                        print('本次只检查初始反馈；请回中并松开数字键，确认就绪后重新操作。', flush=True)
                    else:
                        try:
                            if args.mode == 'hold':
                                execute_hold(arm, action, state, initial, args,
                                             lambda: snapshot(pad.fileno(), key_codes), session)
                            else:
                                execute_step(arm, action, state, initial, args,
                                             lambda: snapshot(pad.fileno(), key_codes))
                        except LimitReached as exc:
                            print(f'{joint}号：{exc}', flush=True)
                        except MotionPaused as exc:
                            print(f'当前动作已取消：{exc} 程序仍在运行。', flush=True)
                        gate = Gate()
                        print('本次处理结束；摇杆回中、数字键松开后等待就绪。', flush=True)
                time.sleep(POLL_SECONDS)
        finally:
            if arm is not None:
                arm.bus.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--move', action='store_true', help='Send real servo commands')
    parser.add_argument('--mode', choices=('step', 'hold'), default='step',
                        help='step: one move per gesture; hold: move while held with proportional stick speed')
    parser.add_argument('--configure-buttons', action='store_true',
                        help='Learn physical buttons 1 and 3, save and exit without arm access')
    parser.add_argument('--joints', type=int, nargs='+', choices=range(1, 7), default=[1],
                        help='Enabled joints; defaults to base only')
    parser.add_argument('--step', type=int, choices=range(1, 17), default=16,
                        help='Degrees per gesture (1-16, default 16); duration scales with step')
    parser.add_argument('--span', type=int, choices=range(1, 91), default=90,
                        help='Allowed degrees either side of initial position (1-90, default 90)')
    parser.add_argument('--speed', type=int, choices=range(5, 21), default=10,
                        help='Requested maximum degrees per second (5-20, default 10)')
    parser.add_argument('--hold-rest-ms', type=int, default=400,
                        help='Bus rest after each hold segment, 50-1000ms (default 400); ignored in step mode')
    args = parser.parse_args(argv)
    if not 50 <= args.hold_rest_ms <= 1000:
        parser.error('--hold-rest-ms must be between 50 and 1000')
    if args.mode == 'step' and args.step > args.span:
        parser.error('--span must be at least --step')
    args.joints = list(dict.fromkeys(args.joints))
    return args


def main():
    args = parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        print('\n已退出；不发送复位或断扭矩指令。')
    except (OSError, RuntimeError) as exc:
        raise SystemExit(f'已停止：{exc}')


if __name__ == '__main__':
    main()
