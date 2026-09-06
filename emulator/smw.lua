-- Verified vanilla SMW WRAM layout. Data reference: IsoFrieze/SMWDisX bank_07.
-- Initialization is completed by the game's own status-1 routine next frame.
return function(api)
  local M = {}
  local hashes = {
    ["6B47BB75D16514B6A476AA0C73A683A2A4C18765"] = true,
    ["7265176858DD9E0C905D4DDC69060E173A23BADD"] = true
  }
  function M.supports(hash)
    return hashes[hash:upper():gsub("^SHA1:", "")] == true
  end
  local function r(a) return api.read("WRAM", a) end
  local function word(a) return r(a) + 256 * r(a + 1) end
  local function active()
    assert(r(0x0100) == 0x14, "Enter a playable level first.")
    assert(r(0x0071) == 0 and r(0x009D) == 0 and r(0x13D4) == 0,
      "Wait until Mario is playing normally (not dying, transforming, or paused).")
  end
  local sprites = {
    star     = {id=0x76, tweaks={0x00,0x00,0x20,0xC2,0x28,0x40}},
    chuck    = {id=0x91, tweaks={0x00,0x0D,0x0B,0xF9,0x11,0x48}},
    mushroom = {id=0x74, tweaks={0x00,0x00,0x08,0xC2,0x28,0x40}},
    flower   = {id=0x75, tweaks={0x00,0x00,0x0A,0xC2,0x28,0x40}},
    one_up   = {id=0x78, tweaks={0x00,0x00,0x0A,0xC2,0x08,0x40}}
  }
  local clear = {
    0xAA,0xB6,0xC2,0x14EC,0x14F8,0x1504,0x1510,0x151C,0x1528,
    0x1534,0x1540,0x154C,0x1558,0x1564,0x1570,0x157C,0x1588,
    0x1594,0x15A0,0x15AC,0x15B8,0x15C4,0x15D0,0x15DC,0x15EA,
    0x15F6,0x1602,0x160E,0x1626,0x1632,0x163E,0x164A,0x1656,
    0x1662,0x166E,0x167A,0x1686,0x186C,0x187B,0x190F,0x1FD6,0x1FE2
  }
  function M.inspect()
    local live = {}
    for i=0,11 do
      if r(0x14C8+i) ~= 0 then
        live[#live+1] = {slot=i, id=r(0x9E+i), status=r(0x14C8+i),
          x=r(0xE4+i)+256*r(0x14E0+i), y=r(0xD8+i)+256*r(0x14D4+i)}
      end
    end
    return {mode=r(0x100), player_state=r(0x71), locked=r(0x9D),
      x=word(0x94), y=word(0x96), camera_x=word(0x1A), camera_y=word(0x1C),
      level=r(0x13BF), powerup=r(0x19), lives=r(0x0DBE)+1,
      coins=r(0x0DBF), sprite_memory=r(0x1692), sprites=live}
  end
  function M.spawn(args)
    active()
    local spec = sprites[args.kind]
    assert(spec, "Supported spawns: star, chuck, mushroom, flower, one_up.")
    local count = args.count
    assert(type(count)=="number" and count==math.floor(count) and count>=1 and count<=10,
      "Choose between 1 and 10 sprites.")
    local slots = {}
    -- Slots 10 and 11 are reserved by several vanilla mechanics.
    for i=9,0,-1 do if r(0x14C8+i)==0 then slots[#slots+1]=i end end
    assert(#slots>=count, "Only "..#slots.." ordinary sprite slots are free; nothing was spawned.")
    local writes, positions = {}, {}
    local function w(a,v) writes[#writes+1]={address=a,value=v} end
    local cx, cy, px, py = word(0x1A), word(0x1C), word(0x94), word(0x96)
    for n=1,count do
      local s = slots[n]
      local x = count==1 and math.max(cx+16,math.min(cx+224,px+8)) or cx+16+math.floor(n*224/(count+1))
      local y = math.max(cy+16,math.min(cy+144,py-64))
      x, y = math.min(65535,x), math.min(65535,y)
      for _,a in ipairs(clear) do w(a+s,0) end
      w(0x9E+s,spec.id)
      w(0xE4+s,x%256); w(0x14E0+s,math.floor(x/256))
      w(0xD8+s,y%256); w(0x14D4+s,math.floor(y/256))
      w(0x161A+s,0xFF) -- Dynamically created, no level loader entry to corrupt.
      w(0x15A0+s,1)
      local tables = {0x1656,0x1662,0x166E,0x167A,0x1686,0x190F}
      for i,a in ipairs(tables) do w(a+s,spec.tweaks[i]) end
      w(0x15F6+s,spec.tweaks[3]%16)
      w(0x157C+s,x>px and 1 or 0)
      w(0x14C8+s,1) -- Publish status last; game executes its INIT routine.
      positions[#positions+1]={slot=s,kind=args.kind,x=x,y=y}
    end
    return writes, {spawned=positions, message="Spawned "..count.." "..args.kind..(count==1 and "" or "s")..".",
      note=args.kind=="chuck" and "Uses the level's loaded graphics and vanilla sprite drawing limits; some tilesets may show incorrect or missing tiles." or ""}
  end
  function M.powerup(value)
    active()
    assert(type(value)=="number" and value==math.floor(value) and value>=0 and value<=3,
      "Powerup must be 0 (small), 1 (big), 2 (cape), or 3 (flower).")
    return {{address=0x19,value=value}}, {message="Changed Mario's powerup.",powerup=value}
  end
  return M
end
