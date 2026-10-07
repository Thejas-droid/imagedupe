"""Create the original overlapping-photo app artwork at Windows icon sizes."""
from pathlib import Path
from PIL import Image, ImageDraw
p=Path(__file__).resolve().parents[2]/'src/imagedupe/assets'
p.mkdir(exist_ok=True)
im=Image.new('RGBA',(1024,1024));d=ImageDraw.Draw(im)
d.rounded_rectangle((32,32,992,992),radius=230,fill='#0c6f69')
# Two distinct photo frames with enough separation to read at 16px.
d.rounded_rectangle((170,175,700,690),radius=60,fill='#80d5c6')
d.rounded_rectangle((205,210,665,655),radius=30,fill='#d7f5eb')
d.polygon([(205,590),(360,390),(515,595),(570,515),(665,625),(665,655),(205,655)],fill='#429f91')
d.rounded_rectangle((325,335,855,850),radius=60,fill='#ffffff')
d.rounded_rectangle((360,370,820,815),radius=30,fill='#dbeeff')
d.ellipse((660,420,755,515),fill='#ffb64c')
d.polygon([(360,760),(505,550),(640,720),(710,625),(820,775),(820,815),(360,815)],fill='#175d77')
im.save(p/'imagedupe.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
im.resize((256,256)).save(p.parents[2]/'release/app-icon.png')
(p/'imagedupe.svg').write_text('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><rect x="32" y="32" width="960" height="960" rx="230" fill="#0c6f69"/><rect x="170" y="175" width="530" height="515" rx="60" fill="#80d5c6"/><rect x="205" y="210" width="460" height="445" rx="30" fill="#d7f5eb"/><path d="M205 590 360 390 515 595 570 515 665 625V655H205Z" fill="#429f91"/><rect x="325" y="335" width="530" height="515" rx="60" fill="white"/><rect x="360" y="370" width="460" height="445" rx="30" fill="#dbeeff"/><circle cx="707.5" cy="467.5" r="47.5" fill="#ffb64c"/><path d="M360 760 505 550 640 720 710 625 820 775V815H360Z" fill="#175d77"/></svg>''',encoding='utf-8')
