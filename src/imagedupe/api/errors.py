from dataclasses import dataclass
@dataclass
class ImageDupeError(Exception):
    code:str; detail:str; status:int=400; title:str="ImageDupe error"
    def problem(self):
        return {"type":f"https://imagedupe.local/problems/{self.code.lower().replace('_','-')}","title":self.title,"status":self.status,"detail":self.detail,"code":self.code}
