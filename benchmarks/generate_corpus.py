"""Generate a small labeled near-duplicate corpus for local benchmark smoke tests."""
from pathlib import Path
from PIL import Image,ImageEnhance,ImageFilter,ImageDraw

def generate(out:Path,count:int=20):
    out.mkdir(parents=True,exist_ok=True);manifest=[]
    for i in range(count):
        base=Image.new('RGB',(256,192),'white');d=ImageDraw.Draw(base);d.rectangle((20+i%50,30,180,120),fill=((i*41)%255,(i*73)%255,(i*29)%255));d.ellipse((80,70,220,180),outline='black',width=5)
        p=out/f'{i:04d}-base.jpg';base.save(p,quality=95);manifest.append((p.name,i,'base'))
        variants=[('q70',lambda x:x),('bright',lambda x:ImageEnhance.Brightness(x).enhance(1.08)),('blur',lambda x:x.filter(ImageFilter.GaussianBlur(.7))),('resize',lambda x:x.resize((192,144)).resize((256,192)))]
        for name,fn in variants:
            q=out/f'{i:04d}-{name}.jpg';fn(base.copy()).save(q,quality=70 if name=='q70' else 92);manifest.append((q.name,i,name))
    (out/'manifest.csv').write_text('file,group,transform\n'+'\n'.join(','.join(map(str,r)) for r in manifest)+'\n')
if __name__=='__main__': generate(Path('benchmark-corpus'))
