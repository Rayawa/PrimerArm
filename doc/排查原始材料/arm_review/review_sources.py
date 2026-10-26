from pathlib import Path
import hashlib, json, re, zipfile
from xml.etree import ElementTree as ET
from pypdf import PdfReader

root = Path('A:/arm')
out = root / 'tmp/arm_review'
out.mkdir(parents=True, exist_ok=True)
ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
docs = [root/'机械臂/香橙派AIpro机械臂垃圾分类实验4.7.docx',
        root/'OrangePi/doc/环境/手把手教你搭建Orange Pi AI Pro开发环境.docx']
for idx, path in enumerate(docs):
    with zipfile.ZipFile(path) as z:
        xml = ET.fromstring(z.read('word/document.xml'))
        paras = [''.join(p.itertext()) for p in []]
        paras = [''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in xml.findall('.//w:p',ns)]
        (out/f'doc{idx}.txt').write_text('\n'.join(p for p in paras if p),encoding='utf-8')
    print('DOC', idx, path.name, len(paras))
pdfs = [root/'Atlas/doc/项目/机械臂应用开发指南.pdf',
        root/'OrangePi/doc/OrangePi_AI_Pro_昇腾_用户手册_v1.2.pdf']
for idx,path in enumerate(pdfs):
    doc=PdfReader(path)
    pages=[p.extract_text() for p in doc.pages]
    (out/f'pdf{idx}.txt').write_text('\n'.join(f'PAGE {i+1}\n{t}' for i,t in enumerate(pages)),encoding='utf-8')
    print('PDF',idx,path.name,'pages',len(pages))
    for i,t in enumerate(pages):
        if re.search('扭矩|掉电|过流|40PIN|40 Pin|排线|I2C7|i2c-7|供电|电源开关',t,re.I):
            print('Relevant page',i+1, re.sub(r'\s+',' ',t)[:100])

main=root/'ros2_robot_arm/ros2_robot_arm'
other=root/'OrangePi/src/ascend-devkit-master/src/E2E-Sample/ros2_robot_arm'
files=[p for p in main.rglob('*') if p.is_file() and p.suffix in {'.py','.sh','.txt','.md','.xml','.cpp','.h','.urdf','.yaml','.ipynb'}]
changed=[]; missing=[]
for p in files:
    q=other/p.relative_to(main)
    if not q.exists(): missing.append(str(p.relative_to(main)))
    elif p.read_bytes()!=q.read_bytes(): changed.append(str(p.relative_to(main)))
print('Source comparison',json.dumps({'compared':len(files),'different':changed,'missing_in_other':missing},ensure_ascii=False))
for p in other.rglob('*.ipynb'):
    if p.name.startswith('._'):continue
    nb=json.loads(p.read_text(encoding='utf-8'))
    text='\n\n'.join(''.join(c['source']) for c in nb['cells'])
    (out/'notebook.txt').write_text(text,encoding='utf-8')
    print('Notebook',p.name,len(text))
