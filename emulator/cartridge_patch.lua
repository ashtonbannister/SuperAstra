-- Loaded-cartridge edits need their own journal: core save states may omit ROM.
return function(api)
  local P={original={},current={}}
  local function copy(t) local r={};for k,v in pairs(t) do r[k]=v end;return r end
  function P.snapshot() return copy(P.current) end
  function P.count() local n=0;for _ in pairs(P.current) do n=n+1 end;return n end
  function P.validate(writes)
    assert(api.write_rom,"This adapter cannot patch the loaded cartridge.")
    assert(type(writes)=="table" and #writes>0 and #writes<=4096,"Patch 1–4096 cartridge bytes at once.")
    local seen={};local count=0;for _ in pairs(P.original) do count=count+1 end
    for _,w in ipairs(writes) do
      assert(type(w)=="table" and type(w.address)=="number" and w.address==math.floor(w.address)
        and w.address>=0 and w.address<api.size("ROM"),"Invalid cartridge file offset.")
      assert(not seen[w.address],"Duplicate cartridge offset.");seen[w.address]=true
      for _,v in ipairs({w.value,w.expected}) do
        assert(type(v)=="number" and v==math.floor(v) and v>=0 and v<=255,"Invalid cartridge byte.")
      end
      assert(w.expected~=nil and w.value~=nil,"Every cartridge write needs expected and replacement bytes.")
      assert(api.read("ROM",w.address)==w.expected,"Cartridge bytes changed. Re-read the code; no writes performed.")
      if P.original[w.address]==nil then count=count+1 end
    end
    assert(count<=65536,"This session's cartridge journal is limited to 64 KiB of distinct bytes.")
    return writes
  end
  function P.apply(writes)
    for _,w in ipairs(writes) do
      if P.original[w.address]==nil then P.original[w.address]=api.read("ROM",w.address) end
      api.write_rom(w.address,w.value)
      assert(api.read("ROM",w.address)==w.value,"Cartridge write verification failed; this core may expose read-only ROM.")
      P.current[w.address]=w.value~=P.original[w.address] and w.value or nil
    end
  end
  function P.restore(snapshot)
    for a,base in pairs(P.original) do
      local desired=snapshot[a];if desired==nil then desired=base end
      if api.read("ROM",a)~=desired then api.write_rom(a,desired) end
      assert(api.read("ROM",a)==desired,"Could not restore cartridge bytes.")
    end
    P.current=copy(snapshot)
  end
  function P.reset(discard)
    if not discard then P.restore({}) end
    P.original={};P.current={}
  end
  return P
end
