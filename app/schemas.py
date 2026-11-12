from typing import Literal, Optional, List
from pydantic import BaseModel, Field, model_validator, field_validator
class ChatMessage(BaseModel):
    id:str; role:Literal['system','user','assistant','tool']; content:str
class SourceText(BaseModel):
    type:Literal['plain','chat']='plain'; content:Optional[str]=None; messages:Optional[List[ChatMessage]]=None
    @model_validator(mode='after')
    def valid_source(self):
        if self.type=='plain' and not (self.content or '').strip(): raise ValueError("text.content required for plain input")
        if self.type=='chat' and not self.messages: raise ValueError("text.messages required for chat input")
        return self
class Options(BaseModel):
    design_theme: Optional[Literal['auto','dark_lime','editorial_purple','corporate_blue','india_yellow','legacy']] = None
    content_mode: Optional[Literal['source','topic']] = None 
    slide_count: Optional[int] = Field(None, ge=2, le=20)
    language: Optional[str] = None
    theme: Optional[str] = None
    theme_style: Optional[Literal["clean", "dark"]] = None
    seed: Optional[int] = None
    font: Optional[str] = None
    brand_colors: Optional[List[str]] = None
    style: Optional[str] = None
    template: Optional[str] = None
    speaker_notes: Optional[bool] = None
    output: List[Literal["pptx", "pdf", "thumbnails"]] = Field(default_factory=lambda: ["pptx", "pdf"])
    @field_validator('brand_colors')
    @classmethod
    def valid_colors(cls, value):
        import re
        if value and any(not re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in value):
            raise ValueError('brand_colors must contain #RRGGBB values')
        return value
class PresentationRequest(BaseModel):
    request_id:str; user_id:str='local-user'; prompt:Optional[str]=None; text:Optional[SourceText]=None; options:Options=Field(default_factory=Options); callback_url:Optional[str]=None
    @model_validator(mode='after')
    def require_content(self):
        from app.services.intent import explicit_intent
        intent = explicit_intent(self.prompt or '')
        if self.options.content_mode is None:
            self.options.content_mode = intent.get('content_mode') or ('source' if self.text is not None else 'topic')
        if self.options.speaker_notes is None:
            self.options.speaker_notes = intent.get('speaker_notes', True)
        if self.text is None:
            if self.options.content_mode != 'topic' or not (self.prompt or '').strip():
                raise ValueError('Provide text, or use options.content_mode=topic with a prompt')
            self.text = SourceText(content=self.prompt)
        return self
class RegenerateRequest(BaseModel):
    prompt:Optional[str]=None; slide_id:Optional[str]=None; instruction:Optional[str]=None
