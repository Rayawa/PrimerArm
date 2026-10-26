#!/usr/bin/env python3
"""Bounded feedback-only diagnosis; never sends motion/reset/torque commands."""
import inspect
import os
from pathlib import Path
import sys
import time


def bus_users():
    found = []
    for process in Path('/proc').glob('[0-9]*'):
        if process.name == str(os.getpid()):
            continue
        try:
            for fd in (process / 'fd').iterdir():
                try:
                    if os.path.realpath(fd) == '/dev/i2c-7':
                        name = (process / 'comm').read_text().strip()
                        found.append((process.name, name))
                        break
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            continue
    return found


def check_bus_users():
    users = bus_users()
    if users:
        for pid, name in users:
            print(f'其它I2C使用者：PID={pid} 名称={name}', flush=True)
        raise RuntimeError('诊断未继续：请先退出这些程序，再重新运行。没有终止任何进程。')
    print('当前未发现其它进程打开 /dev/i2c-7（仅为此刻的检查）。', flush=True)


def query(bus, register, value, delay, word=False):
    # Whitelist exactly the three documented query operations.
    allowed = ((register == 0x01 and value == 1 and not word)
               or (register == 0x38 and 1 <= value <= 6 and not word)
               or (0x31 <= register <= 0x36 and value == 0 and word))
    if not allowed:
        raise ValueError('not a feedback query')
    try:
        bus.write_byte_data(0x15, register, value)
        time.sleep(delay)
        if word:
            raw = bus.read_word_data(0x15, register)
            return ((raw >> 8) & 255) | ((raw & 255) << 8)
        return bus.read_byte_data(0x15, register)
    except OSError as exc:
        return f'{type(exc).__name__}: {exc}'
    finally:
        time.sleep(0.5)  # No rapid retry, including on errors or zero replies.


def collect(bus, delay):
    version = query(bus, 0x01, 1, delay)
    print(f'控制板版本寄存器：{version!r}（原始字节；0不能单独证明板子正常）', flush=True)
    for joint in range(1, 7):
        ping = query(bus, 0x38, joint, delay)
        pos = query(bus, 0x30 + joint, 0, delay, word=True)
        print(f'{joint}号：状态={ping!r}，原始位置={pos!r}', flush=True)


def main():
    if sys.platform != 'linux':
        raise SystemExit('请在香橙派上使用 /usr/bin/python3 运行。')
    import fcntl
    from Arm_Lib import Arm_Device
    print('反馈诊断 diag1：无运动、复位、扭矩或参数修改指令。', flush=True)
    print('安装驱动：', inspect.getfile(Arm_Device), flush=True)
    with open('/tmp/dofbot_gamepad.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        check_bus_users()
        print('先静默10秒。测试期间保持其它机械臂程序关闭，不按归正键。', flush=True)
        time.sleep(10)
        check_bus_users()
        arm = Arm_Device()
        try:
            # A/B/A can reveal time-dependent recovery; does not prove causation.
            for index, delay in enumerate((0.003, 0.05, 0.003), 1):
                if index > 1:
                    time.sleep(5)
                    check_bus_users()
                print(f'\n第{index}/3轮 {time.strftime("%H:%M:%S")}：应答等待{delay * 1000:g}ms', flush=True)
                collect(arm.bus, delay)
        finally:
            arm.bus.close()
    print('\n诊断结束。正常舵机状态应为218；请保留三轮完整输出。', flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n诊断已退出。')
    except (OSError, RuntimeError) as exc:
        raise SystemExit(str(exc))
