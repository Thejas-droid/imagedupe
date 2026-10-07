import io
from pathlib import Path
import pytest
from PIL import Image,ImageDraw,PngImagePlugin
from imagedupe.core.config import Settings
from imagedupe.catalog.db import Catalog
from imagedupe.core.collections import CollectionService
from imagedupe.indexes.manager import IndexManager
from imagedupe.core.search import SearchService

def make_image(path:Path,seed:int=1,metadata=False):
    im=Image.new('RGB',(96,72),'white');d=ImageDraw.Draw(im)
    for i in range(8):
        x=(seed*13+i*17)%80;y=(seed*7+i*11)%55;d.rectangle((x,y,x+10+i,y+8),fill=((seed*31+i*21)%255,(seed*67+i*13)%255,(seed*19+i*33)%255))
    if metadata:
        info=PngImagePlugin.PngInfo();info.add_text('note','different bytes');im.save(path,'PNG',pnginfo=info)
    else:im.save(path,'PNG')
    return path
@pytest.fixture
def env(tmp_path):
    root=tmp_path/'images';root.mkdir();s=Settings(home=tmp_path/'home',worker_count=1);c=Catalog(s.db_path);i=IndexManager(c,s.index_dir,s);cs=CollectionService(c,s);ss=SearchService(c,i,s);return s,c,i,cs,ss,root
