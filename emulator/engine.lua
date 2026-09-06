-- Frame-boundary command engine. The adapter owns file I/O and emulator APIs.
return function(api, smw, token, session, clock, sandbox, cartridge)
  local E = {epoch=0, history={}, holds={}, rules={}, checkpoints={}, seen={}, seen_order={}, internal_load=false}
  local original_hash=api.game().romhash
  local function integer(v,lo,hi,label)
    assert(type(v)=="number" and v==math.floor(v) and v>=lo and v<=hi,
      (label or "Value").." is outside its allowed integer range.")
    return v
  end
  local function copy(t)
    local result={}
    for k,v in pairs(t) do result[k]=type(v)=="table" and copy(v) or v end
    return result
  end
  local function normalize(list,limit,allow_duplicates)
    assert(type(list)=="table" and #list>0 and #list<=limit,"Invalid number of memory bytes.")
    local result, addresses = {}, {}
    for _,item in ipairs(list) do
      assert(type(item)=="table","Invalid memory byte.")
      local a=integer(item.address,0,0x1FFFF,"WRAM address")
      local v=integer(item.value,0,255,"Byte")
      assert(allow_duplicates or not addresses[a],"Duplicate memory address.")
      result[#result+1]={address=a,value=v}; addresses[a]=true
    end
    return result
  end
  local function guards_match(guards)
    for _,g in ipairs(guards or {}) do
      if api.read("WRAM",g.address)~=g.value then return false end
    end
    return true
  end
  function E.context()
    local ctx=api.game()
    ctx.protocol=1;ctx.session=session;ctx.epoch=E.epoch;ctx.frame=api.frame()
    ctx.undo_count=#E.history
    local n=0;for _ in pairs(E.holds) do n=n+1 end;ctx.hold_count=n
    ctx.smw=smw.supports(ctx.romhash) and (not cartridge or cartridge.count()==0)
    ctx.routines={}
    for name,r in pairs(E.rules) do ctx.routines[#ctx.routines+1]={name=name,remaining=r.remaining} end
    ctx.last_routine_error=E.last_routine_error
    ctx.cartridge_patch_bytes=cartridge and cartridge.count() or 0
    ctx.checkpoints={}
    for name,c in pairs(E.checkpoints) do ctx.checkpoints[#ctx.checkpoints+1]={name=name,frame=c.frame} end
    ctx.experiment_running=E.probe~=nil
    return ctx
  end
  function E.invalidate()
    if E.probe then
      -- A ROM/state switch supersedes a temporary branch; do not load an old state.
      pcall(api.drop,E.probe.return_state);E.probe=nil
    end
    for _,h in ipairs(E.history) do pcall(api.drop,h.state) end
    for _,c in pairs(E.checkpoints) do pcall(api.drop,c.state) end
    if cartridge then cartridge.reset(api.game().romhash~=original_hash) end
    original_hash=api.game().romhash
    E.history={};E.holds={};E.rules={};E.checkpoints={};E.probe_result=nil;E.epoch=E.epoch+1
    if api.cancel_observation then api.cancel_observation() end
  end
  local function restore(id,rom)
    E.internal_load=true
    local ok,err=pcall(api.load,id)
    E.internal_load=false
    if not ok then error(err) end
    if cartridge then cartridge.restore(rom or {}) end
  end
  local function transaction(label,fn)
    local snapshot=api.save()
    assert(type(snapshot)=="string" and #snapshot>0,"Could not create an Undo checkpoint; no writes performed.")
    local old_holds=copy(E.holds)
    local old_rules=copy(E.rules)
    local old_rom=cartridge and cartridge.snapshot() or {}
    local ok,result=pcall(fn)
    if not ok then
      E.holds=old_holds
      E.rules=old_rules
      local restored,restore_error=pcall(restore,snapshot,old_rom)
      pcall(api.drop,snapshot)
      if not restored then error("WRITE FAILED AND ROLLBACK FAILED: "..tostring(restore_error)) end
      error(tostring(result).." The pre-command state was restored.")
    end
    E.history[#E.history+1]={state=snapshot,holds=old_holds,rules=old_rules,rom=old_rom,label=label}
    if #E.history>8 then local old=table.remove(E.history,1);pcall(api.drop,old.state) end
    result.undo_count=#E.history
    return result
  end
  local function write_bytes(writes)
    for _,w in ipairs(writes) do api.write(w.address,w.value) end
    -- Check the final value at each address (initializers legitimately repeat).
    local final={};for _,w in ipairs(writes) do final[w.address]=w.value end
    for a,v in pairs(final) do assert(api.read("WRAM",a)==v,"Memory write verification failed.") end
  end
  function E.tick()
    if E.probe and E.probe.restore_failed then return end
    for _,hold in pairs(E.holds) do
      if guards_match(hold.guards) then write_bytes(hold.writes) end
    end
    for name,rule in pairs(E.rules) do
      if rule.last_frame~=api.frame() then
        local before={}
        local ok,err=pcall(function()
          local writes,new_state=sandbox(rule.source,copy(rule.state))
          for _,w in ipairs(writes) do before[#before+1]={address=w.address,value=api.read("WRAM",w.address)} end
          write_bytes(writes)
          rule.state=new_state;rule.last_frame=api.frame()
          if rule.remaining>0 then rule.remaining=rule.remaining-1 end
          if rule.remaining==0 then E.rules[name]=nil end
        end)
        if not ok then
          local restored,restore_error=pcall(function() write_bytes(before) end)
          E.rules[name]=nil
          E.last_routine_error=name..": "..tostring(err)..(restored and "" or " Rollback failed: "..tostring(restore_error))
        end
      end
    end
  end
  local operations={}
  local function ram_copy()
    local chunks={}
    for a=0,0x1FFFF do chunks[#chunks+1]=string.char(api.read("WRAM",a)) end
    return table.concat(chunks)
  end
  local function diff(before,start,length)
    local count=0;local rows={};local pages={}
    for a=start,start+length-1 do
      local old=before:byte(a+1);local value=api.read("WRAM",a)
      if old~=value then
        count=count+1
        local page=math.floor(a/4096)*4096;pages[page]=(pages[page] or 0)+1
        if #rows<128 then rows[#rows+1]={address=string.format("%05X",a),before=old,after=value} end
      end
    end
    local density={};for a,n in pairs(pages) do density[#density+1]={start=string.format("%05X",a),changed_bytes=n} end
    table.sort(density,function(a,b)return a.start<b.start end)
    return {changed_bytes=count,changes=rows,truncated=count>#rows,pages=density,
      range_start=string.format("%05X",start),range_length=length}
  end
  local function checkpoint(name)
    assert(type(name)=="string" and name:match("^[%w_%-]+$") and #name<=48,"Invalid checkpoint name.")
    return assert(E.checkpoints[name],"No checkpoint with that name in this bridge session.")
  end
  local function finish_probe(cancelled)
    local p=E.probe;assert(p,"No experiment is running.")
    local ok,result=pcall(function()
      if cancelled then return {cancelled=true,message="Experiment cancelled; the pre-experiment state was restored."} end
      local observation=api.observation()
      local result={message="Experiment finished and the pre-experiment state was restored. Results describe the temporary branch.",
        observation=observation,branch_frame=api.frame(),diff=diff(p.baseline,0,131072),checkpoint=p.name,
        last_routine_error=E.last_routine_error}
      if api.registers then local good,regs=pcall(api.registers);if good then result.registers=regs end end
      local captured,err=pcall(api.screenshot)
      result.screenshot=captured;if not captured then result.screenshot_error=tostring(err) end
      return result
    end)
    local restored,err=pcall(restore,p.return_state,p.rom)
    p.restore_failed=not restored
    E.holds=p.holds;E.rules=p.rules;E.last_routine_error=p.last_error
    if api.cancel_observation then api.cancel_observation() end
    if restored then pcall(api.drop,p.return_state);E.probe=nil end
    assert(restored,"EXPERIMENT RESTORE FAILED: "..tostring(err)..". Use cancel_experiment to retry restoring.")
    E.probe_result=ok and result or {error=tostring(result),restored=true}
    return E.probe_result
  end
  function E.poll_probe()
    if E.probe and not E.probe.restore_failed and api.observation().done then finish_probe(false);return true end
    return false
  end
  function E.shutdown()
    if E.probe and api.game().romhash==original_hash then finish_probe(true) end
    E.invalidate()
  end
  function operations.create_checkpoint(args)
    assert(type(args.name)=="string" and args.name:match("^[%w_%-]+$") and #args.name<=48,"Invalid checkpoint name.")
    local n=0;for name in pairs(E.checkpoints) do if name~=args.name then n=n+1 end end
    assert(n<4,"Keep up to four named experiment checkpoints.")
    local ram=ram_copy();local id=api.save()
    assert(type(id)=="string" and #id>0,"Could not create checkpoint.")
    local old=E.checkpoints[args.name]
    E.checkpoints[args.name]={state=id,frame=api.frame(),ram=ram,holds=copy(E.holds),rules=copy(E.rules),
      rom=cartridge and cartridge.snapshot() or {}}
    if old then pcall(api.drop,old.state) end
    return {message="Saved experiment checkpoint "..args.name..".",name=args.name,frame=api.frame()}
  end
  function operations.compare_checkpoint(args)
    local c=checkpoint(args.name)
    local length=integer(args.length,1,131072,"Comparison length")
    local start=integer(args.address,0,131072-length,"WRAM offset")
    return {checkpoint=args.name,checkpoint_frame=c.frame,frame=api.frame(),diff=diff(c.ram,start,length)}
  end
  function operations.restore_checkpoint(args)
    local c=checkpoint(args.name)
    local result=transaction("Restore checkpoint "..args.name,function()
      restore(c.state,c.rom);E.holds=copy(c.holds);E.rules=copy(c.rules)
      return {message="Restored checkpoint "..args.name..". Undo can return to the prior live state."}
    end)
    E.epoch=E.epoch+1
    if api.cancel_observation then api.cancel_observation() end
    result.context=E.context()
    return result
  end
  function operations.delete_checkpoint(args)
    local c=checkpoint(args.name);api.drop(c.state);E.checkpoints[args.name]=nil
    return {message="Released checkpoint "..args.name.."."}
  end
  function operations.experiment(args)
    local c=checkpoint(args.name)
    assert(api.observe,"Controlled experiments are unavailable in this adapter.")
    integer(args.frames,1,300,"Experiment frames")
    assert(type(args.addresses)=="table" and #args.addresses<=128,"Watch up to 128 addresses.")
    for _,a in ipairs(args.addresses) do integer(a,0,0x1FFFF,"Watch address") end
    if args.trace_address~=nil then integer(args.trace_address,0,0xFFFFFF,"Trace address") end
    local id=api.save();assert(type(id)=="string" and #id>0,"Could not save return state.")
    E.probe={return_state=id,rom=cartridge and cartridge.snapshot() or {},holds=copy(E.holds),
      rules=copy(E.rules),last_error=E.last_routine_error,baseline=c.ram,name=args.name}
    E.probe_result=nil
    local ok,err=pcall(function()
      restore(c.state,c.rom);E.holds=copy(c.holds);E.rules=copy(c.rules)
      if args.rom_writes and #args.rom_writes>0 then
        assert(cartridge,"Cartridge patches unavailable.");cartridge.apply(cartridge.validate(args.rom_writes))
      end
      if args.source and args.source~="" then local writes=sandbox(args.source,{});write_bytes(writes) end
      args.control_inputs=true;api.observe(args)
    end)
    if not ok then finish_probe(true);error(tostring(err).." The pre-experiment state was restored.") end
    return {message="Testing a temporary branch from "..args.name..".",frames=args.frames}
  end
  function operations.experiment_result(args)
    if E.probe then return {done=false} end
    assert(E.probe_result,"There is no completed experiment.")
    return {done=true,result=E.probe_result}
  end
  function operations.cancel_experiment(args)
    if E.probe then return finish_probe(true) end
    return {message="No experiment is running."}
  end
  function operations.inspect(args)
    local ctx=E.context()
    if ctx.smw then ctx.game_state=smw.inspect() end
    if api.registers then local ok,regs=pcall(api.registers);if ok then ctx.registers=regs end end
    return ctx
  end
  function operations.disassemble(args)
    assert(api.disassemble,"The selected core does not provide disassembly.")
    local pc=integer(args.address,0,0xFFFFFF,"CPU address")
    local count=integer(args.count,1,128,"Instruction count")
    return api.disassemble(pc,count)
  end
  function operations.observe(args)
    assert(api.observe,"Observation is unavailable in this adapter.")
    integer(args.frames,1,300,"Observation frames")
    assert(type(args.addresses)=="table" and #args.addresses<=128,"Watch up to 128 addresses.")
    for _,a in ipairs(args.addresses) do integer(a,0,0x1FFFF,"Watch address") end
    if args.trace_address~=nil then integer(args.trace_address,0,0xFFFFFF,"Trace address") end
    return api.observe(args)
  end
  function operations.observation(args) return api.observation() end
  function operations.export_rom(args)
    assert(api.export_rom,"Cartridge export unavailable in this adapter.")
    return api.export_rom()
  end
  function operations.read(args)
    local domain=args.domain or "WRAM"
    assert(domain=="WRAM" or domain=="ROM" or (api.domain_allowed and api.domain_allowed(domain)),"This hardware memory domain is not exposed.")
    local length=integer(args.length,1,4096,"Read length")
    local start=integer(args.address,0,api.size(domain)-length,"Read address")
    local bytes={};for i=0,length-1 do bytes[#bytes+1]=api.read(domain,start+i) end
    return {domain=domain,address=start,bytes=bytes,frame=api.frame()}
  end
  function operations.dump(args)
    local chunks={}
    for a=0,0x1FFFF do chunks[#chunks+1]=string.format("%02x",api.read("WRAM",a)) end
    return {hex=table.concat(chunks),context=E.context()}
  end
  function operations.patch(args)
    local writes=normalize(args.writes,1024,false)
    local expected=normalize(args.expected,1024,false)
    local coverage={};for _,g in ipairs(expected) do coverage[g.address]=true end
    for _,w in ipairs(writes) do assert(coverage[w.address],"Every write needs an expected byte.") end
    assert(guards_match(expected),"Memory changed since it was inspected. Read it again; no writes performed.")
    return transaction("Memory patch",function()
      write_bytes(writes)
      return {message="Applied "..#writes.." memory bytes.",bytes_written=#writes}
    end)
  end
  function operations.patch_rom(args)
    assert(cartridge,"Cartridge patching unavailable in this adapter.")
    local writes=cartridge.validate(args.writes)
    return transaction("Cartridge patch",function()
      cartridge.apply(writes)
      return {message="Applied "..#writes.." loaded-cartridge bytes. Verify the affected game behavior.",bytes_written=#writes}
    end)
  end
  function operations.hold(args)
    assert(type(args.name)=="string" and args.name:match("^[%w_%-]+$") and #args.name<=48,"Invalid cheat name.")
    local writes=normalize(args.writes,128,false)
    local expected=normalize(args.expected,128,false)
    local coverage={};for _,g in ipairs(expected) do coverage[g.address]=true end
    for _,w in ipairs(writes) do assert(coverage[w.address],"Every held byte needs an expected byte.") end
    local guards={}
    if args.guards and #args.guards>0 then guards=normalize(args.guards,32,false) end
    assert(guards_match(expected),"Memory changed. Read it again before freezing.")
    local total=#writes
    local occupied={}
    for name,hold in pairs(E.holds) do
      if name~=args.name then
        total=total+#hold.writes
        for _,w in ipairs(hold.writes) do occupied[w.address]=true end
      end
    end
    assert(total<=128,"At most 128 bytes can be held at once.")
    for _,w in ipairs(writes) do assert(not occupied[w.address],"Another cheat already holds this address.") end
    return transaction("Freeze "..args.name,function()
      E.holds[args.name]={writes=writes,guards=guards}
      if guards_match(guards) then write_bytes(writes) end
      return {message="Holding "..args.name.." until stopped or a state/ROM is loaded.",name=args.name}
    end)
  end
  function operations.stop_holds(args)
    return transaction("Stop cheats",function()
      if args.name and args.name~="" then E.holds[args.name]=nil;E.rules[args.name]=nil
      else E.holds={};E.rules={};if cartridge then cartridge.restore({}) end end
      return {message="Stopped requested effects. Stopping all also removes loaded-cartridge patches. WRAM values remain until Undo or normal game updates."}
    end)
  end
  function operations.routine(args)
    assert(sandbox,"Generated routines are not available in this adapter.")
    assert(type(args.name)=="string" and args.name:match("^[%w_%-]+$") and #args.name<=48,"Invalid routine name.")
    local frames=integer(args.frames,0,216000,"Routine duration")
    local count=0;for name in pairs(E.rules) do if name~=args.name then count=count+1 end end
    assert(count<4,"At most four frame routines may run at once.")
    local writes,state=sandbox(args.source,{})
    return transaction("Routine "..args.name,function()
      write_bytes(writes)
      if frames~=1 then E.rules[args.name]={source=args.source,state=state,remaining=frames==0 and -1 or frames-1,last_frame=api.frame()}
      else E.rules[args.name]=nil end
      E.last_routine_error=nil
      return {message="Executed "..args.name..(frames==1 and "." or "; frame routine is active."),bytes_written=#writes,name=args.name}
    end)
  end
  function operations.spawn(args)
    assert(not cartridge or cartridge.count()==0,"Loaded cartridge patches are active. Reassess spawning with the general tools.")
    assert(smw.supports(api.game().romhash),"Spawning needs the verified Super Mario World profile for this exact ROM.")
    local writes,result=smw.spawn(args)
    writes=normalize(writes,1024,true)
    return transaction("Spawn "..args.kind,function() write_bytes(writes);return result end)
  end
  function operations.powerup(args)
    assert(not cartridge or cartridge.count()==0,"Loaded cartridge patches are active. Reassess the powerup field with the general tools.")
    assert(smw.supports(api.game().romhash),"This command needs the verified Super Mario World profile.")
    local writes,result=smw.powerup(args.value)
    return transaction("Mario powerup",function() write_bytes(writes);return result end)
  end
  function operations.undo(args)
    local h=E.history[#E.history]
    assert(h,"There is no Undo checkpoint in this bridge session.")
    restore(h.state,h.rom)
    E.holds=h.holds;E.rules=h.rules or {};table.remove(E.history);pcall(api.drop,h.state)
    E.epoch=E.epoch+1
    if api.cancel_observation then api.cancel_observation() end
    return {message="Undid "..h.label..". The entire game rewound to just before that command.",undo_count=#E.history,context=E.context()}
  end
  function operations.screenshot(args)
    api.screenshot()
    return {message="Captured the current emulator screen.",file="screen.png"}
  end
  function E.handle(request)
    local id=type(request)=="table" and request.id or "invalid"
    local ok,result=pcall(function()
      assert(type(request)=="table" and type(id)=="string" and id:match("^[a-f0-9]+$") and #id==32,"Invalid request id.")
      assert(request.protocol==1 and request.token==token,"Invalid bridge protocol or token. Restart the app and script together.")
      assert(request.session==session,"The Lua bridge restarted. Reconnect before sending another command.")
      assert(request.romhash==api.game().romhash and request.epoch==E.epoch,"Game context changed. Read the current state before making another change.")
      assert(type(request.expires)=="number" and clock()<=request.expires and request.expires<=clock()+30,"Request expired; no operation performed.")
      assert(not E.seen[id],"Duplicate command rejected.")
      E.seen[id]=true;E.seen_order[#E.seen_order+1]=id
      if #E.seen_order>256 then E.seen[table.remove(E.seen_order,1)]=nil end
      assert(type(request.args)=="table","Invalid command arguments.")
      local fn=operations[request.op];assert(fn,"Unknown command.")
      if E.probe then
        if request.op=="undo" or request.op=="stop_holds" then finish_probe(true)
        else assert(request.op=="inspect" or request.op=="experiment_result" or request.op=="cancel_experiment",
          "A temporary experiment is running. Wait for its result or cancel it first.") end
      end
      return fn(request.args)
    end)
    return {id=id,ok=ok,result=ok and result or nil,error=not ok and tostring(result) or nil}
  end
  return E
end
