#!/usr/bin/env python3
"""Read Linux gamepad events and preview joint selection; no arm access."""
import argparse
import glob
import os
import select
import struct

EVENT = struct.Struct('@llHHi')
AXES = {0: 128, 1: 128, 2: 128, 5: 128}
NAMES = {1: '底座', 2: '大臂', 3: '小臂', 4: '腕部', 5: '末端旋转', 6: '夹爪'}


def find_pad():
    matches = []
    for path in glob.glob('/sys/class/input/event*/device/id/vendor'):
        with open(path) as f:
            vendor = f.read().strip()
        with open(os.path.join(os.path.dirname(path), 'product')) as f:
            product = f.read().strip()
        if (vendor, product) == ('0810', '0001'):
            event = path.split('/')[-4]
            matches.append('/dev/input/' + event)
    if len(matches) != 1:
        raise SystemExit('未找到唯一的 0810:0001 手柄，请运行 cat /proc/bus/input/devices 检查。')
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', help='Optional event device path')
    args = parser.parse_args()
    path = args.device or find_pad()
    axes = AXES.copy()
    keys = {292: False, 293: False}
    previous = None
    print('仅预览，不访问机械臂。请保持 ANALOG 模式。', flush=True)
    print('L1 按住启用；左摇杆控制 1/2 号，右摇杆控制 3/4 号。', flush=True)
    print('同时按住 R1 时，右摇杆改为控制 5/6 号。Ctrl+C 退出。', flush=True)
    print('设备：' + path, flush=True)
    with open(path, 'rb', buffering=0) as device:
        while True:
            if not select.select([device], [], [], 1)[0]:
                continue
            data = device.read(EVENT.size)
            if len(data) != EVENT.size:
                raise SystemExit('手柄已断开，预览结束。')
            _, _, kind, code, value = EVENT.unpack(data)
            if kind == 0 and code == 3:
                raise SystemExit('输入事件丢失，请重新启动预览。')
            if kind == 3 and code in axes:
                axes[code] = value
            elif kind == 1 and code in keys:
                keys[code] = bool(value)
            elif kind == 0 and code == 0:
                if not keys[292]:
                    message = '未启用（按住 L1 才预览关节指令）'
                else:
                    mapping = {0: 1, 1: 2, 5: 5 if keys[293] else 3,
                               2: 6 if keys[293] else 4}
                    parts = []
                    for axis, joint in mapping.items():
                        delta = axes[axis] - 128
                        if abs(delta) > 25:
                            direction = '角度增加' if delta > 0 else '角度减小'
                            parts.append(f'{joint}号{NAMES[joint]}：{direction}')
                    message = ' | '.join(parts) if parts else '已启用，摇杆回中'
                if message != previous:
                    print(message, flush=True)
                    previous = message


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n预览结束。')
