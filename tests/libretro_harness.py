#!/usr/bin/env python3
"""Headless libretro harness: execute the real Snes9x core, capture video/audio,
and drive authentic controller inputs. This is development QA, not game code.
"""
from pathlib import Path
import ctypes as C
import numpy as np
from PIL import Image
import wave, json
ROOT=Path(__file__).resolve().parent

class GameInfo(C.Structure):
 _fields_=[('path',C.c_char_p),('data',C.c_void_p),('size',C.c_size_t),('meta',C.c_char_p)]
class Variable(C.Structure):
 _fields_=[('key',C.c_char_p),('value',C.c_char_p)]
class SystemInfo(C.Structure):
 _fields_=[('name',C.c_char_p),('version',C.c_char_p),('extensions',C.c_char_p),('need_fullpath',C.c_bool),('block_extract',C.c_bool)]
class Geometry(C.Structure):
 _fields_=[('base_width',C.c_uint),('base_height',C.c_uint),('max_width',C.c_uint),('max_height',C.c_uint),('aspect_ratio',C.c_float)]
class Timing(C.Structure):
 _fields_=[('fps',C.c_double),('sample_rate',C.c_double)]
class AVInfo(C.Structure):
 _fields_=[('geometry',Geometry),('timing',Timing)]
class Emulator:
 BUTTONS={'B':0,'Y':1,'SELECT':2,'START':3,'UP':4,'DOWN':5,'LEFT':6,'RIGHT':7,'A':8,'X':9,'L':10,'R':11}
 def __init__(self,core=None,rom=None):
  assert core and rom, 'Pass explicit core and ROM paths for live QA'
  self.lib=C.CDLL(str(core))
  self.buttons=set();self.audio=[];self.frames=[];self.latest=None;self.pixel=0;self.n=0
  self.capture=False;self.sample_frames=False;self.sink=None
  self.strings=[str(ROOT/'work').encode(),b'0',b'1']
  ENV=C.CFUNCTYPE(C.c_bool,C.c_uint,C.c_void_p)
  VID=C.CFUNCTYPE(None,C.c_void_p,C.c_uint,C.c_uint,C.c_size_t)
  AUD=C.CFUNCTYPE(None,C.c_int16,C.c_int16)
  BATCH=C.CFUNCTYPE(C.c_size_t,C.POINTER(C.c_int16),C.c_size_t)
  POLL=C.CFUNCTYPE(None)
  INPUT=C.CFUNCTYPE(C.c_int16,C.c_uint,C.c_uint,C.c_uint,C.c_uint)
  def env(cmd,data):
   if cmd==10:self.pixel=C.cast(data,C.POINTER(C.c_int)).contents.value;return True
   if cmd in [9,30,31]:C.cast(data,C.POINTER(C.c_char_p))[0]=self.strings[0];return True
   if cmd==3:C.cast(data,C.POINTER(C.c_bool))[0]=False;return True
   if cmd==15:
    v=C.cast(data,C.POINTER(Variable)).contents
    # Default options are declared by SET_VARIABLES; a null response requests default.
    return False
   if cmd==17:C.cast(data,C.POINTER(C.c_bool))[0]=False;return True
   if cmd==(47|0x10000):C.cast(data,C.POINTER(C.c_int))[0]=3;return True
   if cmd==(49|0x10000):C.cast(data,C.POINTER(C.c_bool))[0]=False;return True
   if cmd==(51|0x10000):return True
   if cmd in [16,18,11,35,36,37,44,45,53,65]:return True
   return False
  def video(data,w,h,pitch):
   if not data:return
   if self.pixel==1:
    raw=np.frombuffer(C.string_at(data,pitch*h),np.uint8).reshape(h,pitch)[:,:w*4].reshape(h,w,4);rgb=raw[:,:,[2,1,0]].copy()
   else:
    raw=np.frombuffer(C.string_at(data,pitch*h),np.uint16).reshape(h,pitch//2)[:,:w]
    if self.pixel==2:rgb=np.stack([((raw>>11)&31)*255//31,((raw>>5)&63)*255//63,(raw&31)*255//31],2).astype(np.uint8)
    else:rgb=np.stack([((raw>>10)&31)*255//31,((raw>>5)&31)*255//31,(raw&31)*255//31],2).astype(np.uint8)
   self.latest=rgb
   if self.sink:self.sink(rgb)
   if self.sample_frames:self.frames.append(rgb)
  def batch(data,n):
   if self.capture:self.audio.append(np.ctypeslib.as_array(data,shape=(n*2,)).copy().reshape(n,2))
   return n
  def audio(l,r):
   if self.capture:self.audio.append(np.array([[l,r]],dtype=np.int16))
  def inp(port,dev,index,bid):
   if port!=0:return 0
   if bid==256:return sum(1<<b for b in self.buttons)
   return int(bid in self.buttons)
  self.callbacks=[ENV(env),VID(video),AUD(audio),BATCH(batch),POLL(lambda:None),INPUT(inp)]
  for name,cb in zip(['environment','video_refresh','audio_sample','audio_sample_batch','input_poll','input_state'],self.callbacks):
   f=getattr(self.lib,'retro_set_'+name);f.argtypes=[type(cb)];f(cb)
  self.lib.retro_init()
  info=SystemInfo();self.lib.retro_get_system_info(C.byref(info))
  self.core_name=info.name.decode();self.core_version=info.version.decode()
  self.lib.retro_get_memory_data.restype=C.c_void_p
  self.lib.retro_get_memory_data.argtypes=[C.c_uint]
  self.lib.retro_get_memory_size.restype=C.c_size_t
  self.lib.retro_get_memory_size.argtypes=[C.c_uint]
  self.lib.retro_load_game.argtypes=[C.POINTER(GameInfo)];self.lib.retro_load_game.restype=C.c_bool
  rompath=Path(rom).resolve()
  self.rombytes=rompath.read_bytes();self.rombuf=C.create_string_buffer(self.rombytes)
  info=GameInfo(str(rompath).encode(),C.cast(self.rombuf,C.c_void_p),len(self.rombytes),None)
  assert self.lib.retro_load_game(C.byref(info)),'ROM did not load'
  av=AVInfo();self.lib.retro_get_system_av_info(C.byref(av))
  self.fps=av.timing.fps;self.sample_rate=av.timing.sample_rate
  self.lib.retro_set_controller_port_device(0,1)
  addr=self.lib.retro_get_memory_data(2)
  self.wram=(C.c_uint8*self.lib.retro_get_memory_size(2)).from_address(addr) if addr else None
  addr=self.lib.retro_get_memory_data(0)
  self.sram=(C.c_uint8*self.lib.retro_get_memory_size(0)).from_address(addr) if addr else None
 def run(self,n=1,buttons=()):
  self.buttons={self.BUTTONS[b] for b in buttons}
  for _ in range(n):self.lib.retro_run();self.n+=1
 def press(self,b):self.run(2,[b]);self.run(2)
 def word(self,addr):
  if self.wram is None:raise RuntimeError(f'{self.core_name} does not expose WRAM through libretro')
  return self.wram[addr]+256*self.wram[addr+1]
 def status(self):
  return dict(frame=self.n,mode=self.wram[0x100],x=self.word(0x94),y=self.word(0x96),power=self.wram[0x19],level=self.wram[0x13bf],state=self.wram[0x71])
 def save(self,path):
  self.lib.retro_serialize_size.restype=C.c_size_t
  size=self.lib.retro_serialize_size(); buf=C.create_string_buffer(size)
  self.lib.retro_serialize.argtypes=[C.c_void_p,C.c_size_t]
  assert self.lib.retro_serialize(buf,size)
  Path(path).write_bytes(buf.raw)
 def load(self,path):
  b=Path(path).read_bytes(); buf=C.create_string_buffer(b)
  self.lib.retro_unserialize.argtypes=[C.c_void_p,C.c_size_t]
  assert self.lib.retro_unserialize(buf,len(b))
 def shot(self,name,scale=3):
  p=ROOT/'work'/name;Image.fromarray(self.latest).resize((self.latest.shape[1]*scale,self.latest.shape[0]*scale),Image.Resampling.NEAREST).save(p);return p
 def sound(self,path):
  a=np.concatenate(self.audio) if self.audio else np.zeros((0,2),dtype=np.int16)
  with wave.open(str(path),'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(round(self.sample_rate));w.writeframes(a.tobytes())
  return {'samples':len(a),'peak':int(abs(a.astype(np.int32)).max()) if len(a) else 0,'rms':float(np.sqrt(np.mean(a.astype(float)**2))) if len(a) else 0,'clipped':int((abs(a.astype(np.int32))>=32760).sum())}
 def close(self):self.lib.retro_unload_game();self.lib.retro_deinit()

