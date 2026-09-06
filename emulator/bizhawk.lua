return function(root)
  local json=dofile(root.."/emulator/json.lua")
  local folder=root.."/ipc/"
  local function read_json(path)
    local f=io.open(path,"rb");if not f then return nil end
    local raw=f:read(300000);f:close()
    local ok,data=pcall(json.decode,raw);if ok then return data end
    return nil
  end
  local function write_json(path,data)
    local temp=path..".lua.tmp"
    local f=assert(io.open(temp,"wb"));f:write(json.encode(data));f:close()
    -- Lua's os.rename does not replace an existing file on Windows.
    os.remove(path);assert(os.rename(temp,path))
  end
  local config=read_json(folder.."config.json")
  assert(config and config.protocol==1,"Start Astra SNES (run.py) first, then reload this script.")
  assert(emu.getsystemid()=="SNES","Load a SNES game before starting Astra SNES.")
  assert(memorysavestate and memorysavestate.savecorestate,"Use a current BizHawk release with memorysavestate support.")
  local domains={}
  for _,name in pairs(memory.getmemorydomainlist()) do domains[name]=true end
  assert(domains.WRAM and memory.getmemorydomainsize("WRAM")==131072,
    "This SNES core does not expose the expected 128 KiB WRAM domain. Select BSNES in BizHawk.")
  local rom_domain=domains.CARTROM and "CARTROM" or domains.ROM and "ROM" or nil
  -- Expose console memory only. Some cores also list host/Waterbox memory pages.
  local hardware={WRAM=true,VRAM=true,OAM=true,CGRAM=true,APURAM=true,ARAM=true,
    CARTRAM=true,SRAM=true,CARTROM=true,ROM=true,["SA1 IRAM"]=true,["SA1 BWRAM"]=true}
  local api={}
  function api.domain_allowed(domain) return hardware[domain] and domains[domain] or false end
  local function resolve(domain)
    if domain=="ROM" then assert(rom_domain,"This core has no readable ROM domain.");return rom_domain end
    assert(api.domain_allowed(domain),"Unknown or unexposed hardware memory domain.")
    return domain
  end
  function api.read(domain,a)
    return memory.read_u8(a,resolve(domain))
  end
  function api.write(a,v) memory.write_u8(a,v,"WRAM") end
  if rom_domain then function api.write_rom(a,v) memory.write_u8(a,v,rom_domain) end end
  function api.size(domain)
    return memory.getmemorydomainsize(resolve(domain))
  end
  function api.game()
    local exposed={}
    for name in pairs(domains) do
      if hardware[name] then exposed[#exposed+1]={name=name,size=memory.getmemorydomainsize(name),readable=true} end
    end
    table.sort(exposed,function(a,b)return a.name<b.name end)
    return {romhash=gameinfo.getromhash(),title=gameinfo.getromname(),system=emu.getsystemid(),
      rom_readable=rom_domain~=nil,rom_size=rom_domain and api.size("ROM") or 0,wram_size=131072,
      memory_domains=exposed,
      capabilities={screenshot=true,registers=true,disassemble=emu.disassemble~=nil,
        write_trace=event.on_bus_write~=nil,routines=true,checkpoints=true,experiments=true,
        cartridge_patch=rom_domain~=nil}}
  end
  function api.frame() return emu.framecount() end
  function api.registers() return emu.getregisters() end
  function api.disassemble(pc,count)
    local rows={}
    for i=1,count do
      local decoded=emu.disassemble(pc)
      assert(decoded and decoded.length and decoded.length>0,"This core does not provide usable disassembly.")
      rows[#rows+1]={address=string.format("%06X",pc),text=decoded.disasm,length=decoded.length}
      pc=math.floor(pc/65536)*65536+(pc+decoded.length)%65536
    end
    return {instructions=rows,note="Uses the core's current 65816 M/X flags. Recheck instruction lengths at mode changes and alternate entry points."}
  end
  local observation=nil
  local buttons={"Up","Down","Left","Right","Start","Select","A","B","X","Y","L","R"}
  function api.cancel_observation()
    if observation and observation.callback then event.unregisterbyid(observation.callback) end
    observation=nil
  end
  function api.observe(args)
    assert(not observation or observation.done,"An observation is already running.")
    api.cancel_observation()
    local pressed={}
    for _,name in ipairs(args.buttons or {}) do
      local valid=false;for _,allowed in ipairs(buttons) do if name==allowed then valid=true end end
      assert(valid,"Unknown SNES button.");pressed[name]=true
    end
    observation={start=emu.framecount(),frames=args.frames,addresses=args.addresses,
      pressed=pressed,control_inputs=args.control_inputs,samples={},writes={},done=false}
    if args.trace_address~=nil then
      local ok,id=pcall(function()
        assert(event.on_bus_write,"Write callbacks unavailable in this BizHawk version.")
        return event.on_bus_write(function(addr,val,flags)
          if observation and #observation.writes<128 then
            observation.writes[#observation.writes+1]={address=addr,value=val,frame=emu.framecount(),registers=emu.getregisters()}
          end
        end,args.trace_address,"Astra SNES write probe")
      end)
      if ok and id and id~="" then observation.callback=id else observation.trace_error=tostring(id) end
    end
    return {message="Observation started.",frames=args.frames}
  end
  function api.observation()
    assert(observation,"There is no observation. Start one first.")
    return {done=observation.done,samples=observation.done and observation.samples or {},
      writes=observation.done and observation.writes or {},trace_error=observation.trace_error,
      elapsed=emu.framecount()-observation.start}
  end
  local function observe_tick()
    if not observation or observation.done then return end
    local elapsed=emu.framecount()-observation.start
    if elapsed>0 then
      local sample={frame=emu.framecount(),values={}}
      for _,a in ipairs(observation.addresses) do sample.values[#sample.values+1]=api.read("WRAM",a) end
      -- Keep at most 60 evenly spaced samples plus the last sample.
      if elapsed%math.max(1,math.ceil(observation.frames/60))==0 or elapsed==observation.frames then
        observation.samples[#observation.samples+1]=sample
      end
    end
    if elapsed>=observation.frames then
      observation.done=true
      if observation.callback then event.unregisterbyid(observation.callback);observation.callback=nil end
    elseif observation.control_inputs or next(observation.pressed) then
      local values={};for _,name in ipairs(buttons) do values[name]=observation.pressed[name] or false end
      joypad.set(values,1)
    end
  end
  function api.save() return memorysavestate.savecorestate() end
  function api.load(id) memorysavestate.loadcorestate(id) end
  function api.drop(id) memorysavestate.removestate(id) end
  function api.export_rom()
    assert(rom_domain,"This core has no readable cartridge domain.")
    local size=api.size("ROM");assert(size<=16777216,"Cartridge exceeds the 16 MiB export limit.")
    local f=assert(io.open(folder.."cartridge.bin","wb"))
    local ok,err=pcall(function()
      for offset=0,size-1,32768 do
        f:write(memory.read_bytes_as_binary_string(offset,math.min(32768,size-offset),rom_domain))
      end
    end)
    f:close();assert(ok,err)
    return {size=size,file="cartridge.bin"}
  end
  function api.screenshot()
    os.remove(folder.."screen.png");client.screenshot(folder.."screen.png")
    local f=io.open(folder.."screen.png","rb");assert(f,"Screenshot was not written by BizHawk.");f:close()
  end
  local session=tostring(os.time()).."-"..tostring(os.clock()).."-"..tostring({})
  local smw=dofile(root.."/emulator/smw.lua")(api)
  local sandbox=dofile(root.."/emulator/sandbox.lua")(api)
  local cartridge=dofile(root.."/emulator/cartridge_patch.lua")(api)
  local engine=dofile(root.."/emulator/engine.lua")(api,smw,config.token,session,os.time,sandbox,cartridge)
  os.remove(folder.."request.json");os.remove(folder.."response.json")
  local last_hash=gameinfo.getromhash()
  local last_frame=emu.framecount()
  if event and event.onloadstate then
    event.onloadstate(function() if not engine.internal_load then engine.invalidate() end end,"Astra SNES: state change")
  end
  if event and event.onexit then
    event.onexit(function() engine.shutdown();os.remove(folder.."heartbeat.json") end,"Astra SNES: close")
  end
  console.log("Astra SNES connected. Keep emulation running; use the companion app to send prompts.")
  local ticks=0
  while true do
    local hash,frame=gameinfo.getromhash(),emu.framecount()
    if hash~=last_hash or frame<last_frame then engine.invalidate();last_hash=hash end
    if emu.getsystemid()~="SNES" then
      write_json(folder.."heartbeat.json",{protocol=1,error="Load a SNES game and restart the Lua bridge."})
      break
    end
    local ok,err=pcall(function()
      local request=read_json(folder.."request.json")
      if request then
        os.remove(folder.."request.json")
        write_json(folder.."response.json",engine.handle(request))
        ticks=0 -- Publish current context immediately, including a new Undo epoch.
      end
      engine.tick()
      observe_tick()
      if engine.poll_probe() then ticks=0 end
      if ticks%30==0 then write_json(folder.."heartbeat.json",engine.context()) end
    end)
    if not ok then
      engine.holds={}
      console.log("Astra SNES: "..tostring(err))
      write_json(folder.."heartbeat.json",{protocol=1,error=tostring(err)})
    end
    last_frame=emu.framecount();ticks=ticks+1
    emu.frameadvance()
  end
end
