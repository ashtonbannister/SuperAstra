-- Generated game logic runs in a capability-limited Lua environment.
-- It can only read cartridge/RAM bytes, stage WRAM writes, and retain small data.
-- It has no filesystem, network, debug, loading, metatables, or host references.
return function(api)
  local function int(n,lo,hi)
    assert(type(n)=="number" and n==math.floor(n) and n>=lo and n<=hi,"Invalid routine integer.")
    return n
  end
  local function check_state(value,depth,seen,budget)
    budget.n=budget.n+1;assert(budget.n<=1024 and depth<=8,"Routine state is too large.")
    local t=type(value)
    if t=="table" then
      assert(not seen[value] and not getmetatable(value),"Routine state must be acyclic plain data.")
      seen[value]=true
      for k,v in pairs(value) do
        assert(type(k)=="string" or type(k)=="number","Invalid state key.")
        if type(k)=="string" then assert(#k<=128,"State key too long.") end
        check_state(v,depth+1,seen,budget)
      end
      seen[value]=nil
    elseif t=="string" then assert(#value<=1024,"State string too long.")
    elseif t=="number" then assert(value==value and math.abs(value)<1e15,"Invalid state number.")
    else assert(t=="nil" or t=="boolean","State may only contain data, not functions.") end
  end
  return function(source,state)
    assert(type(source)=="string" and #source>0 and #source<=20000,"Routine source must be 1–20000 bytes.")
    local staged,order={},{}
    local env={state=state or {},frame=api.frame(),assert=assert,error=error,
      ipairs=ipairs,pairs=pairs,next=next,type=type,tonumber=tonumber,
      math={floor=math.floor,ceil=math.ceil,min=math.min,max=math.max,abs=math.abs,sqrt=math.sqrt}}
    function env.read(a,width)
      width=int(width or 1,1,4);a=int(a,0,0x20000-width)
      local value=0
      for i=0,width-1 do value=value+(staged[a+i] or api.read("WRAM",a+i))*256^i end
      return value
    end
    function env.rom(a)
      return api.read("ROM",int(a,0,api.size("ROM")-1))
    end
    function env.write(a,value,width)
      width=int(width or 1,1,4);a=int(a,0,0x20000-width)
      value=int(value,0,256^width-1)
      for i=0,width-1 do
        if staged[a+i]==nil then order[#order+1]=a+i end
        assert(#order<=512,"Routine exceeded 512 written bytes per frame.")
        staged[a+i]=math.floor(value/256^i)%256
      end
    end
    local fn,err=load(source,"Astra game routine","t",env)
    assert(fn,err)
    local previous_hook,mask,count=debug.gethook()
    debug.sethook(function() error("Routine exceeded its instruction budget.") end,"",50000)
    local ok,result=pcall(fn)
    debug.sethook(previous_hook,mask,count)
    assert(ok,result)
    check_state(env.state,0,{}, {n=0})
    assert(type(env.state)=="table","state must be a table.")
    local writes={}
    for _,a in ipairs(order) do writes[#writes+1]={address=a,value=staged[a]} end
    return writes,env.state
  end
end
