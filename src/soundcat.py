"""v2.1 sound catalogue: every sound the game can play from the artist's library (see docs/SOUND_LIBRARY.md).

Each entry becomes one request file for the MOSS-SoundEffect batch worker (soundlib.write_requests).  `key` is what the game
code asks for; a key without a library sound falls back to the procedural sound of the same name (audio.build) or to `fb`.
Prompts are English, describe ONE sound without music or speech, and say "no speech/music" because the model likes to add both.
Loops are 20-30 s ("seamless"), one-shots 1-6 s.  Every sound gets several seeds; the game picks a different one each time."""

NO = " No speech, no music."
CATALOG = []                  # (key, folder, loop, seconds, versions, prompt, level, fallback)


def _s(key, folder, secs, n, prompt, lvl=1.0, fb=None, loop=False, tail=NO):
    CATALOG.append((key, folder, loop, secs, n, prompt + tail, lvl, fb))


def _loop(key, folder, prompt, secs=24, n=6, lvl=1.0, fb=None):
    _s(key, folder, secs, n, prompt + " Steady, continuous, seamless loop, no sudden loud events.", lvl, fb, True)


# ------------------------------------------------------------------ engines (loops; the game changes pitch with speed)
for k, desc in (
        ("engine_i4", "a mid-size petrol four-cylinder family hatchback"),
        ("engine_small", "a tiny rattly old two-stroke style economy car (Yugo, Trabant) with a buzzy tinny engine"),
        ("engine_v8", "a big rumbling V8 muscle car with a deep burble"),
        ("engine_diesel", "an old clattering diesel van or SUV"),
        ("engine_truck", "a heavy diesel lorry or tractor with a deep chugging rumble"),
        ("engine_ev", "an electric car, a smooth rising electric motor whine")):
    _loop(k, "vehicles/engines", f"Engine of {desc} driving at constant moderate revs, recorded close from outside the car.", 8, 6, 0.9)
_s("engine_start", "vehicles/engines", 3, 8, "A car engine cranking and starting up, then settling to idle.", 0.9)
_s("car_passby_slow", "vehicles/passby", 6, 8, "A car driving slowly past a microphone on an asphalt street, engine and tyre rolling noise, left to right.", 0.9)
_s("car_passby_fast", "vehicles/passby", 5, 8, "A car speeding past a microphone on a street with a rising and falling doppler engine roar.", 1.0)
_s("truck_passby", "vehicles/passby", 7, 6, "A heavy lorry rumbling past a microphone with air brakes hiss.", 1.0)
_loop("tyre_roll_asphalt", "vehicles/tyres", "Tyres rolling on rough asphalt, a steady road hum, recorded beside the road.", 16, 5, 0.6)
_loop("tyre_gravel", "vehicles/tyres", "Car tyres rolling slowly over a gravel road, crunching stones.", 16, 5, 0.6)
_loop("screech", "vehicles/tyres", "A car tyre skidding and squealing on asphalt in a tight turn, continuous screech.", 4, 8, 0.8)
_s("car_door_open", "vehicles/doors", 1.5, 8, "A car door being opened, handle click and hinge creak.", 0.8)
_s("car_door_close", "vehicles/doors", 1.5, 8, "A car door being closed, a solid thunk.", 0.8)
_s("car_door_slam", "vehicles/doors", 1.5, 8, "A car door slammed hard in anger, a loud bang.", 0.9)
_s("handbrake", "vehicles/doors", 1.5, 6, "A ratcheting mechanical car handbrake being pulled.", 0.7)
_s("car_alarm", "vehicles/misc", 10, 6, "A car alarm blaring with changing siren patterns.", 0.9)
_s("kerb_bump", "vehicles/misc", 1.5, 8, "A car tyre bumping hard over a kerb, a dull thud and suspension clunk.", 0.8, "crash")
# horns
_s("horn", "vehicles/horns", 1.2, 8, "A short honk of a normal car horn, one beep.", 0.8)
_s("horn_small", "vehicles/horns", 1.0, 6, "A small high-pitched beep of a tiny city car horn.", 0.7)
_s("horn_truck", "vehicles/horns", 2.0, 6, "A deep long blast of a lorry air horn.", 0.9)
_s("horn_jingle", "vehicles/horns", 4, 6, "A cheerful musical car horn jingle of a wedding convoy or ice cream van, honking melody.", 0.7, tail="")
# sirens (loops)
_loop("siren_police", "vehicles/sirens", "A police car siren with fast yelp wail, passing in an open street.", 12, 5, 0.8)
_loop("siren_amb", "vehicles/sirens", "An ambulance siren with the classic two-tone hi-lo pattern.", 12, 5, 0.8)
_loop("siren_fire", "vehicles/sirens", "A fire engine siren, slow rising and falling wail with an air horn blast now and then.", 12, 5, 0.8)
_s("siren_distant", "vehicles/sirens", 8, 8, "A faraway emergency siren in a city, muffled by buildings.", 0.4)
_s("train_horn_distant", "vehicles/misc", 6, 5, "A distant diesel train horn echoing over a city.", 0.5)

# ------------------------------------------------------------------ weapons and fighting
_s("shot_pistol", "weapons", 2.0, 10, "A single pistol gunshot outdoors in a city street with a short echo.", 0.9, "shot")
_s("shot_uzi", "weapons", 2.0, 8, "A burst of submachine gun fire, rapid shots outdoors with echo.", 0.9, "shot")
_s("shot_shotgun", "weapons", 2.5, 8, "A loud shotgun blast outdoors with a pump action reload.", 1.0, "shot")
_s("shot_kalash", "weapons", 2.5, 8, "A burst of assault rifle fire outdoors, sharp cracks with echo.", 1.0, "shot")
_s("shot_distant", "weapons", 3.0, 8, "A faraway gunshot in a city, dull and echoing between buildings.", 0.5, "shot")
_s("shot", "weapons", 2.0, 8, "A single gunshot outdoors, sharp crack with an echo.", 0.9)
_s("rocket_launch", "weapons", 3.0, 6, "A rocket launcher firing with a whooshing launch and hiss.", 1.0, "boom")
_s("bat_hit", "weapons", 1.0, 8, "A baseball bat hitting something solid with a dull thud.", 0.9, "punch")
_s("bullet_ricochet", "weapons", 1.5, 8, "A bullet ricocheting off a concrete wall with a whine.", 0.7)
_s("bullet_wall", "weapons", 1.0, 6, "A bullet hitting a plaster wall with a dull crack and crumbling.", 0.6)
_s("punch", "fight", 1.0, 10, "A fist punching a body, a dull fleshy thud.", 0.9)
_s("kick", "fight", 1.0, 10, "A heavy kick hitting a body with a thump and a grunt-free impact.", 0.9)
_s("swing", "fight", 1.0, 8, "A fist or arm swinging through the air, a quick whoosh.", 0.5, "punch")
_s("body_fall", "fight", 1.5, 8, "A person falling and landing hard on pavement, a heavy thud.", 0.9, "punch")
_s("body_hit_car", "fight", 1.5, 8, "A car hitting a pedestrian, a heavy body thud with a metal bump.", 1.0, "punch")
_s("cpr_pump", "fight", 3.0, 4, "Rhythmic chest compressions, dull rhythmic pressing thumps.", 0.5)

# ------------------------------------------------------------------ impacts, destruction, fire, water
_s("crash", "impacts", 3.0, 10, "A car crash, heavy metal crunch and shattering glass.", 1.0)
_s("crash_light", "impacts", 1.5, 10, "A light car bump, a dull plastic and metal knock.", 0.8, "crash")
_s("crash_glass", "impacts", 2.5, 8, "A window shattering into many pieces of glass on pavement.", 0.9, "crash")
_s("crash_metal", "impacts", 2.0, 8, "A heavy metal clang, a car hitting a steel barrier or lamp post.", 0.9, "crash")
_s("crash_wood", "impacts", 2.0, 8, "A wooden fence or kiosk splintering and falling over.", 0.8, "crash")
_s("tree_break", "impacts", 3.0, 8, "A small tree trunk snapping and branches rustling and falling.", 0.9, "crash")
_s("prop_thud", "impacts", 1.2, 8, "A dull thud of something light being knocked over onto the pavement.", 0.7, "punch")
_s("bin_clang", "impacts", 2.0, 8, "A metal rubbish bin being knocked over, rolling and clanging.", 0.8)
_s("glass_bottle", "impacts", 2.0, 6, "A glass bottle rolling and clinking on pavement.", 0.6)
_s("boom", "explosions", 4.0, 8, "A large explosion of a car with a deep boom and debris falling afterwards.", 1.0)
_s("boom_distant", "explosions", 5.0, 6, "A big explosion far away rumbling over a city.", 0.5, "boom")
_s("boom_rocket", "explosions", 4.0, 6, "A rocket explosion with a sharp blast, then debris rattling.", 1.0, "boom")
_loop("fire_crackle", "explosions", "A large fire crackling and roaring, popping wood, from several metres away.", 20, 5, 0.7)
_loop("spray", "water", "A fire hose spraying a strong jet of water onto a burning car, hissing steam.", 12, 5, 0.8)
_s("splash", "water", 2.0, 8, "A person or small object falling into a river with a splash.", 0.9)
_s("splash_big", "water", 3.0, 8, "A whole car falling into a river with a huge splash and bubbling.", 1.0, "splash")
_s("swim_stroke", "water", 6.0, 5, "A person swimming through a river, rhythmic splashing.", 0.6)
_s("puddle_step", "water", 1.0, 8, "A single footstep stepping into a puddle of water.", 0.5)

# ------------------------------------------------------------------ pickups, shops, UI
_s("chime", "pickups", 1.2, 6, "A bright friendly game pickup chime, two quick bell tones.", 0.6, tail=" No speech.")
_s("tick", "pickups", 0.6, 4, "A single short clean click, a button tick.", 0.5, tail="")
_s("pick", "pickups", 1.5, 6, "A rising magical game pickup sparkle, short.", 0.6, tail=" No speech.")
_s("cash", "pickups", 1.5, 8, "Coins and banknotes handed over, a cash register ka-ching.", 0.7)
_s("eat", "pickups", 2.0, 8, "A person biting and crunching a crispy pastry, chewing.", 0.7)
_s("revive", "pickups", 1.5, 5, "A gentle uplifting healing sparkle, short magical rising tones.", 0.6, tail=" No speech.")

# ------------------------------------------------------------------ people, steps, crowds (no words)
for k, desc in (("step_asphalt", "walking on hard asphalt pavement"), ("step_grass", "walking on dry grass"),
                ("step_wood", "walking on a wooden bridge deck"), ("step_dirt", "walking on a dry dirt path"),
                ("step_run_asphalt", "running fast on asphalt")):
    _s(k, "steps", 1.0, 10, f"A single footstep of a person {desc}, one step only.", 0.5)
_s("crowd_cheer", "crowd", 6, 8, "A crowd of people cheering and clapping outdoors, no intelligible words.", 0.8)
_s("crowd_laugh", "crowd", 5, 6, "A group of friends laughing together outdoors, no words.", 0.7)
_s("crowd_panic", "crowd", 6, 6, "A distant crowd screaming in panic and running, no intelligible words.", 0.8)
_s("crowd_applause", "crowd", 6, 6, "A small crowd applauding in a square.", 0.7)
_s("crowd_football_roar", "crowd", 10, 6, "A football stadium crowd roaring after a goal, with drums and whistles.", 0.8)
_s("kids_laugh", "crowd", 5, 6, "Children laughing and squealing while playing, no words.", 0.6)
_s("baby_cry", "crowd", 5, 4, "A baby crying in a flat or on the street.", 0.5)
_s("whistle_ref", "crowd", 2, 5, "A referee whistle blast.", 0.6)
_s("coughing", "crowd", 3, 5, "A person coughing a smoker's cough.", 0.4)
_s("sneeze", "crowd", 1.5, 4, "A person sneezing.", 0.4)
_s("clap_hands", "crowd", 2, 4, "A few people clapping once or twice.", 0.5)

# ------------------------------------------------------------------ birds and animals (one-shots; the game places them in trees, parks, the river)
for k, secs, n, desc in (
        ("bird_crow", 4, 10, "A hooded crow cawing three or four times from a tree"),
        ("bird_crow_flock", 8, 8, "A flock of crows cawing noisily over a city park at dusk"),
        ("bird_magpie", 4, 8, "A magpie chattering with a harsh rattling call"),
        ("bird_dove", 5, 10, "A collared dove cooing softly from a rooftop"),
        ("bird_pigeon", 5, 8, "Pigeons cooing and ruffling on a city square"),
        ("bird_pigeon_flock_takeoff", 4, 8, "A flock of pigeons flapping their wings and taking off at once"),
        ("bird_sparrow", 5, 8, "Many house sparrows chirping in a bush"),
        ("bird_swallow", 5, 6, "Swallows twittering as they fly past over a city in summer"),
        ("bird_swift", 6, 6, "Swifts screaming high above rooftops on a summer evening"),
        ("bird_blackbird", 8, 8, "A blackbird singing a flute-like melody at dawn"),
        ("bird_nightingale", 10, 6, "A nightingale singing at night from a thicket"),
        ("bird_songbird_day", 10, 8, "Small songbirds singing in a park in spring"),
        ("bird_tit", 4, 6, "A great tit calling with a bright two-note song"),
        ("bird_cuckoo", 6, 6, "A cuckoo calling in a forest"),
        ("bird_woodpecker", 4, 6, "A woodpecker drumming on a tree trunk"),
        ("bird_owl", 6, 8, "A tawny owl hooting at night in a forest"),
        ("bird_owl_little", 5, 6, "A little owl calling at night over a village"),
        ("bird_duck", 3, 10, "A single mallard duck quacking on a river"),
        ("bird_duck_flock", 10, 10, "Several mallard ducks quacking and paddling on the Vardar river"),
        ("bird_duck_takeoff", 4, 6, "Ducks splashing and flapping as they take off from the water"),
        ("bird_goose", 5, 6, "Geese honking on a riverbank"),
        ("bird_swan", 4, 4, "A swan hissing and wings flapping on a lake"),
        ("bird_seagull", 5, 6, "Seagulls crying over a lake"),
        ("bird_heron", 3, 4, "A grey heron croaking as it flies low over a river"),
        ("bird_stork_clatter", 6, 6, "A white stork clattering its bill on a nest"),
        ("bird_rooster", 5, 8, "A rooster crowing in a village in the morning"),
        ("bird_hen", 6, 5, "Hens clucking in a farm yard"),
        ("bird_jay", 4, 6, "A jay screeching in a forest"),
        ("bird_hoopoe", 4, 4, "A hoopoe calling with a repeated hoo-poo-poo"),
        ("bird_wings_flap", 3, 8, "A single bird taking off from a branch with a quick flutter of wings"),
        ("bird_hawk", 5, 6, "A hawk screeching high in the sky")):
    _s(k, "birds", secs, n, desc + ".", 0.6)
_loop("birds", "birds", "A calm daytime park full of small birds twittering and singing in the trees, with distant traffic far away.", 30, 6, 0.6)
_loop("amb_dawn_chorus", "birds", "A busy dawn chorus of many birds singing in a green park at sunrise.", 30, 6, 0.6)
for k, secs, n, desc in (
        ("dog", 3, 10, "A single dog barking twice in a street"),
        ("dog_small", 3, 8, "A small yappy dog barking quickly"),
        ("dog_big", 3, 8, "A big dog barking in a deep voice behind a fence"),
        ("dog_growl", 3, 6, "A dog growling and snarling aggressively"),
        ("dog_howl", 6, 6, "A dog howling at night"),
        ("dog_pack_distant", 8, 6, "Stray dogs barking back and forth at night far away"),
        ("cat_meow", 3, 8, "A cat meowing"),
        ("cat_fight", 5, 6, "Two cats fighting and screeching at night"),
        ("cow_bell", 8, 5, "Cow bells ringing on a mountain pasture"),
        ("sheep_bleat", 6, 5, "Sheep and goats bleating on a hillside"),
        ("donkey", 5, 4, "A donkey braying"),
        ("horse_neigh", 4, 5, "A horse neighing and snorting"),
        ("frog_croak", 8, 6, "A few frogs croaking at a pond"),
        ("rat_squeak", 2, 4, "A rat squeaking and scurrying in rubbish"),
        ("bee_buzz", 6, 4, "A bee buzzing past and hovering around flowers"),
        ("fly_buzz", 5, 4, "A fly buzzing around a room")):
    _s(k, "animals", secs, n, desc + ".", 0.6)
_loop("crickets", "animals", "Crickets chirping rhythmically on a warm summer night in a meadow.", 24, 6, 0.5)
_loop("cicadas", "animals", "Cicadas buzzing loudly in the trees on a hot summer afternoon.", 24, 6, 0.5)
_loop("frog_chorus", "animals", "A chorus of frogs croaking by a pond at night.", 24, 5, 0.5)

# ------------------------------------------------------------------ ambience loops (the game mixes them by place, density and time of day)
_loop("city", "ambience/city", "Distant city hum of a big Balkan city seen from a rooftop: traffic wash, far-off horns and indistinct life.", 30, 6, 0.6)
_loop("traffic", "ambience/city", "Busy boulevard traffic passing close by on asphalt, cars and buses whooshing, occasional horn.", 30, 6, 0.7)
_loop("amb_traffic_jam", "ambience/city", "A traffic jam, slow idling engines, honking and exhaust rumble.", 30, 5, 0.7)
_loop("amb_street_quiet", "ambience/city", "A quiet residential side street in the afternoon with a distant car and a distant TV.", 30, 5, 0.5)
_loop("amb_street_night", "ambience/city", "A quiet city street at night, distant traffic hum, a far dog, a cat, hollow echoes.", 30, 6, 0.5)
_loop("amb_bridge_traffic", "ambience/city", "Standing on a bridge over a river, traffic rumbling on the deck, wind and flowing water below.", 30, 5, 0.6)
_loop("amb_courtyard", "ambience/city", "A residential courtyard between apartment blocks, distant kids, a window opening, a bit of echo.", 30, 5, 0.5)
_loop("amb_industrial", "ambience/city", "An industrial zone, machinery hum, a distant clank and a diesel generator.", 30, 5, 0.6)
_loop("amb_railway", "ambience/city", "Beside a railway line with occasional wind and wire hum, a freight train slowly passing far away.", 30, 4, 0.5)
_loop("crowd", "ambience/people", "A crowd of many people talking at a busy outdoor market, an unintelligible murmur.", 30, 6, 0.7)
_loop("amb_cafe_terrace", "ambience/people", "A cafe terrace with people chatting, cups clinking, laughter, unintelligible murmur.", 30, 6, 0.6)
_loop("amb_bazaar", "ambience/people", "The old bazaar of Skopje, crowds chatting, coppersmiths tapping, footsteps on cobbles, shopkeepers calling unintelligible.", 30, 6, 0.7)
_loop("amb_square_day", "ambience/people", "A big city square on a sunny day, fountains, pigeons, footsteps, crowd murmur.", 30, 6, 0.6)
_loop("amb_playground", "ambience/people", "A playground with children playing, shouting and laughing, swings creaking, unintelligible.", 30, 5, 0.6)
_loop("amb_football_pitch", "ambience/people", "A small football pitch on a weekend, a ball kicks, shouts, a whistle, unintelligible.", 24, 4, 0.5)
_loop("amb_night_party", "ambience/people", "Distant muffled music thumping from a club far away and people outside laughing at night.", 30, 5, 0.4, None)
_loop("amb_market_morning", "ambience/people", "A green market in the morning, stall holders and shoppers, crates, scales, unintelligible murmur.", 30, 5, 0.6)
_s("amb_wedding_distant", "ambience/people", 24, 5, "Distant Macedonian folk wedding celebration with drums (tapan), a zurla shawm and cheering far away.", 0.5, loop=True, tail=" No speech.")
_s("street_musician_accordion", "ambience/people", 20, 5, "A street musician playing a lively Balkan accordion tune in a pedestrian street, with passing footsteps.", 0.5, loop=True, tail=" No speech.")
_loop("amb_park_day", "ambience/nature", "A city park on a sunny day, birds, leaves rustling, distant children and a jogger.", 30, 6, 0.6)
_loop("amb_forest_day", "ambience/nature", "A mixed forest on a summer day, many birds, leaves rustling in a light breeze, an occasional woodpecker.", 30, 6, 0.6)
_loop("amb_forest_night", "ambience/nature", "A forest at night, crickets, an owl hooting far away, rustling leaves and low wind.", 30, 6, 0.5)
_loop("amb_meadow_day", "ambience/nature", "An open meadow on a warm day, grasshoppers, bees and a light breeze.", 30, 5, 0.5)
_loop("amb_hill_wind", "ambience/nature", "Wind blowing over a mountain hillside with grass and distant cow bells.", 30, 5, 0.5)
_loop("wind", "ambience/weather", "Wind blowing through the streets of a city, gentle gusts rising and falling.", 30, 6, 0.5)
_loop("amb_wind_trees", "ambience/weather", "Wind rustling in the leaves of tall trees, gentle to medium.", 30, 6, 0.5)
_s("wind_gust", "ambience/weather", 6, 8, "A single strong gust of wind sweeping through trees.", 0.5)
_s("fireworks_distant", "ambience/weather", 8, 6, "Distant fireworks popping and crackling over a city at night, no music.", 0.4)
_loop("amb_river_vardar", "ambience/water", "A medium-sized river flowing steadily past, with gentle ripples and bank sounds, seen from a stone embankment.", 30, 6, 0.6)
_loop("amb_river_ducks", "ambience/water", "A river with ducks quacking, paddling and splashing, flowing water and distant city.", 30, 6, 0.6)
_loop("amb_lake_shore", "ambience/water", "Small waves lapping at a lake shore with distant seagulls and ducks.", 30, 4, 0.5)
_loop("amb_creek", "ambience/water", "A small creek babbling over stones in a forest.", 30, 4, 0.5)

# ------------------------------------------------------------------ construction and working sounds
_loop("construction", "construction", "A building site, a concrete mixer truck drum rumbling, distant hammering, an angle grinder and clanks of steel.", 30, 6, 0.8)
_s("hammer", "construction", 4, 8, "A worker hammering nails into wood, irregular hammer blows.", 0.7)
_s("hammer_steel", "construction", 4, 6, "A heavy hammer striking steel rebar with ringing blows.", 0.7)
_s("drill", "construction", 5, 6, "An electric hammer drill drilling into concrete.", 0.7)
_loop("jackhammer", "construction", "A pneumatic jackhammer breaking asphalt continuously from some distance.", 20, 4, 0.8)
_s("angle_grinder", "construction", 5, 5, "An angle grinder cutting through steel with sparks, whine.", 0.7)
_s("saw_wood", "construction", 5, 4, "A hand saw cutting through a wooden plank.", 0.5)
_s("shovel_gravel", "construction", 4, 6, "A shovel digging into gravel and sand and throwing it into a pile.", 0.6)
_s("metal_clank", "construction", 2, 10, "A metal pipe or scaffolding tube clanking and ringing when dropped.", 0.7)
_s("truck_reverse_beep", "construction", 6, 5, "A construction truck reversing with a steady beeping warning alarm.", 0.6)
_s("crane_hum", "construction", 10, 4, "A tower crane motor humming and lifting with chain clinks.", 0.5)
_loop("concrete_mixer", "construction", "A concrete mixer truck with a rotating drum, grumbling diesel engine and gravel churning.", 24, 5, 0.7)
_s("fence_rattle", "construction", 3, 6, "A corrugated metal fence rattling as it is knocked.", 0.6)
_s("wheelbarrow", "construction", 5, 4, "A creaky wheelbarrow being pushed over gravel.", 0.5)
_s("tin_roof_bang", "construction", 3, 5, "A loose sheet of tin roofing banging in the wind.", 0.6)

# ------------------------------------------------------------------ city events, bells, voices-free life
_s("bell", "city", 8, 8, "A church bell tolling slowly, two deep strokes.", 0.7)
_s("clock_tower", "city", 10, 4, "A big tower clock striking the hour with a deep bell, mechanical ticking before.", 0.6)
_s("window_open", "city", 2, 6, "A wooden window opening with a creak and a latch click.", 0.4)
_s("shutter_roll", "city", 3, 5, "A metal shop shutter rolling up with a rattle.", 0.6)
_s("door_slam", "city", 1.5, 6, "A heavy apartment building door slamming.", 0.7, "punch")
_s("door_knock", "city", 2, 5, "Knuckles knocking on a wooden door.", 0.4)
_s("door", "city", 1.2, 6, "A wooden door opening and closing with a click.", 0.6, "punch")
_s("tv_apartment", "city", 12, 4, "Muffled TV sound coming from inside an apartment, indistinct.", 0.3, tail=" Words unintelligible.")
_s("laundry_flap", "city", 6, 4, "Laundry sheets flapping on a clothesline in the wind.", 0.4)
_s("scooter_bell", "city", 1.5, 4, "A bicycle bell ringing twice.", 0.4)
_s("bicycle_pass", "city", 4, 5, "A bicycle passing by, chain whirr and tyres on asphalt.", 0.4)
_s("sweeper_machine", "city", 14, 4, "A street sweeping truck with rotating brushes slowly passing.", 0.6)
_s("garbage_truck", "city", 14, 4, "A garbage truck compactor crushing rubbish with hydraulic whine and bottle crash.", 0.7)
_s("street_lamp_buzz", "city", 12, 3, "An old street lamp humming and buzzing at night.", 0.3, loop=True)
_s("power_transformer_hum", "city", 20, 3, "An electrical substation transformer humming at 50 hertz.", 0.3, loop=True)
_s("neon_buzz", "city", 12, 3, "A neon shop sign buzzing and flickering.", 0.3, loop=True)
# ------------------------------------------------------------------ game events and interface (audit of every sim event, round 2)
_s("bullet_car_ping", "weapons", 1.0, 8, "A bullet hitting a car body panel with a sharp metallic ping.", 0.7)
_s("bullet_tree", "weapons", 1.0, 6, "A bullet thudding into a tree trunk with a dull wooden thwack.", 0.6)
_s("bullet_ground", "weapons", 1.0, 6, "A bullet kicking into dirt and gravel with a soft puff.", 0.5)
_s("bullet_flesh", "weapons", 1.0, 6, "A bullet hitting a body with a dull wet thump, no scream.", 0.7, "punch")
_s("hurt_thud", "fight", 1.0, 8, "A person taking a hard knock, a dull body impact with a short breathy exhale.", 0.8, "punch")
_s("defib_zap", "fight", 2.0, 5, "A defibrillator charging whine and a sharp electric zap.", 0.6)
_s("fuel_warning", "vehicles/misc", 2.0, 5, "A car dashboard low fuel warning, two soft electronic beeps.", 0.5, "chime")
_s("fuel_pour", "vehicles/misc", 3.0, 5, "Petrol being poured into a car tank from a jerrycan, glugging.", 0.6, "chime")
_s("engine_stall", "vehicles/engines", 2.5, 6, "A car engine coughing and stalling, then dying out.", 0.8)
_s("fire_ignite", "vehicles/misc", 2.5, 6, "A car catching fire with a whoosh of flames igniting.", 0.8)
_s("fire_out_hiss", "vehicles/misc", 4.0, 5, "A fire dying out under foam with a long hiss and crackle.", 0.7)
_s("bus_door", "vehicles/bus", 2.0, 6, "Bus doors opening and closing with a pneumatic hiss and a clunk.", 0.8)
_s("bus_air_brake", "vehicles/bus", 3.0, 6, "A city bus stopping with a long pneumatic air brake hiss.", 0.9)
_s("weapon_pickup", "weapons", 1.2, 5, "A metallic cocking and loading click of a gun being picked up.", 0.7, "chime")
_s("teleport_whoosh", "interface", 1.5, 5, "A soft airy whoosh as if the view jumps across a map.", 0.5, "chime", tail=" No speech.")
_s("map_paper", "interface", 1.2, 5, "A paper city map being unfolded and rustled.", 0.5)
_s("denied_buzz", "interface", 1.0, 5, "A short soft negative buzz for not enough money.", 0.5, tail=" No speech.")
_s("ui_click", "interface", 0.5, 5, "A soft clean menu tick.", 0.4, tail=" No speech.")
_s("ui_confirm", "interface", 0.8, 5, "A soft confirming menu tone, short and pleasant.", 0.5, tail=" No speech.")
_loop("amb_pigeons_square", "birds", "Pigeons cooing and fluttering on a busy square with distant footsteps.", 24, 5, 0.5)
_loop("amb_city_far", "ambience/city", "The whole city heard from high above: a muffled low rumble of distant traffic, soft steady wind, no individual sounds or details.", 30, 6, 0.6)
_loop("amb_wind_high", "ambience/weather", "Wind blowing steadily at height over rooftops, a soft airy rush with a low rumble, no details.", 30, 5, 0.5)


# ------------------------------------------------------------------ game-feel pass
# MOSS-SoundEffect takes short, concrete descriptions (its own examples are one plain sentence) and renders whatever scene words it is given, so
# anything that reads cinematic (echo, outdoors, huge, over a city ...) makes a sound with a room and a tail.  This pass keeps each prompt to the
# sound itself, appends one fixed style tail (dry / close-up / sharp attack / no tail for one-shots, seamless and even for loops) and caps one-shot
# lengths so clips are short and punchy.  Loops and ambiences keep their length.
_CUT = (r" outdoors", r" in a (city )?street", r" in a city", r" with (a short |an )?echo( between buildings)?", r",? echoing( between buildings| over (a|the) \w+)?", r" echoing",
        r" reverberat\w+", r" over a city", r" with a long ring", r"\bhuge\b", r"\bgiant\b", r" cinematic", r", recorded (close|from)[^.,]*", r" from some distance",
        r" and debris (falling|rattling) afterwards", r", then debris rattling", r" then settling to idle")
_TAIL_SHOT = ", short punchy movie sound effect"
_TAIL_RING = ", short movie sound effect"
_TAIL_LOOP = ", lively ambience with small random sounds"
_TAIL_STEADY = ", steady constant sound"
_RING = ("bell", "clock_tower", "horn", "chime", "pick", "revive", "ui_", "teleport", "denied", "fuel_warning", "defib", "cow_bell", "whistle", "train_horn", "siren_", "car_alarm", "truck_reverse")
_CAP = (("step_", 0.6), ("puddle", 0.5), ("shot_uzi", 1.5), ("shot_kalash", 1.5), ("shot_shotgun", 1.2), ("shot_distant", 1.2), ("shot", 1.0), ("rocket_launch", 1.5), ("bullet_", 0.6),
        ("bat_hit", 0.5), ("swing", 0.4), ("punch", 0.5), ("kick", 0.5), ("body_fall", 0.7), ("body_hit_car", 0.8), ("hurt_thud", 0.5), ("defib", 1.5), ("cpr", 2.0),
        ("crash_light", 0.8), ("crash_glass", 1.5), ("crash_metal", 1.2), ("crash_wood", 1.2), ("crash", 1.5), ("tree_break", 1.5), ("prop_thud", 0.6), ("bin_clang", 1.2),
        ("glass_bottle", 1.0), ("boom", 2.5), ("chime", 0.6), ("tick", 0.5), ("pick", 0.6), ("cash", 0.7), ("eat", 1.0), ("revive", 0.8), ("ui_", 0.5), ("teleport", 0.6),
        ("denied", 0.5), ("map_paper", 0.8), ("fuel_warning", 0.6), ("fuel_pour", 2.0), ("weapon_pickup", 0.6), ("car_door", 0.7), ("horn_jingle", 2.5), ("horn_small", 0.5),
        ("horn_truck", 1.2), ("horn", 0.7), ("engine_start", 2.0), ("engine_stall", 1.5), ("bus_door", 1.2), ("bus_air_brake", 1.8), ("kerb_bump", 0.6), ("car_alarm", 4.0),
        ("fire_ignite", 1.5), ("fire_out", 2.5), ("car_passby", 4.0), ("truck_passby", 5.0), ("siren_distant", 4.0), ("train_horn", 4.0), ("splash_big", 2.0), ("splash", 1.2),
        ("swim", 3.0), ("bell", 5.0), ("clock_tower", 4.0), ("bird_nightingale", 4.0), ("bird_blackbird", 3.0), ("bird_songbird", 3.0), ("bird_duck_flock", 3.0),
        ("bird_crow_flock", 3.0), ("bird_owl", 2.5), ("bird_", 2.0), ("dog_pack", 4.0), ("dog_howl", 3.0), ("dog", 1.5), ("cat_fight", 3.0), ("cat_", 1.5), ("crowd_", 3.0),
        ("kids_laugh", 2.5), ("baby_cry", 2.5), ("hammer", 1.5), ("drill", 2.0), ("angle_grinder", 2.0), ("saw_wood", 2.0), ("shovel", 1.5), ("metal_clank", 1.0),
        ("truck_reverse", 3.0), ("fence_rattle", 1.5), ("wheelbarrow", 2.5), ("tin_roof", 1.5), ("thunder", 3.0), ("wind_gust", 3.0), ("fireworks", 3.0))
_GROUP_CAP = {"animals": 2.0, "birds": 2.0, "crowd": 3.0, "city": 2.5, "vehicles/doors": 0.8, "vehicles/misc": 2.5, "construction": 2.0, "water": 2.0, "impacts": 1.5,
              "weapons": 1.2, "fight": 0.7, "steps": 0.6, "pickups": 0.8, "interface": 0.5, "shops": 1.5, "explosions": 2.5}


SIMPLE = {
    'engine_i4': 'old car engine idling',
    'engine_small': 'old rattly small car engine',
    'engine_v8': 'loud sports car engine',
    'engine_diesel': 'old diesel van engine',
    'engine_truck': 'big truck engine',
    'engine_ev': 'electric car hum',
    'engine_start': 'old car engine starting',
    'car_passby_slow': 'car driving by',
    'car_passby_fast': 'car speeding by',
    'truck_passby': 'truck driving by',
    'tyre_roll_asphalt': 'tyres rolling on road',
    'tyre_gravel': 'tyres on gravel',
    'screech': 'tyre screech',
    'car_door_open': 'car door opening',
    'car_door_close': 'car door closing',
    'car_door_slam': 'car door slam',
    'handbrake': 'handbrake pull',
    'car_alarm': 'car alarm',
    'kerb_bump': 'car bumping a curb',
    'horn': 'angry car horn',
    'horn_small': 'small car horn',
    'horn_truck': 'truck horn',
    'horn_jingle': 'funny car horn tune',
    'siren_police': 'police siren',
    'siren_amb': 'ambulance siren',
    'siren_fire': 'fire truck siren',
    'siren_distant': 'siren far away',
    'train_horn_distant': 'train horn far away',
    'shot_pistol': 'pistol shot',
    'shot_uzi': 'machine gun burst',
    'shot_shotgun': 'shotgun shot',
    'shot_kalash': 'rifle burst',
    'shot_distant': 'gunshot far away',
    'shot': 'gunshot',
    'rocket_launch': 'rocket launch',
    'bat_hit': 'bat hit',
    'bullet_ricochet': 'bullet ricochet',
    'bullet_wall': 'bullet hitting wall',
    'punch': 'punch',
    'kick': 'kick',
    'swing': 'whoosh',
    'body_fall': 'body falling down',
    'body_hit_car': 'car hitting a man',
    'cpr_pump': 'chest pumping',
    'crash': 'car crash',
    'crash_light': 'small car bump',
    'crash_glass': 'glass breaking',
    'crash_metal': 'metal crash',
    'crash_wood': 'wood breaking',
    'tree_break': 'branch snapping',
    'prop_thud': 'thud',
    'bin_clang': 'trash can falling',
    'glass_bottle': 'bottle rolling',
    'boom': 'explosion',
    'boom_distant': 'explosion far away',
    'boom_rocket': 'big explosion',
    'fire_crackle': 'fire crackling',
    'spray': 'water hose',
    'splash': 'splash',
    'splash_big': 'big splash',
    'swim_stroke': 'swimming',
    'puddle_step': 'step in puddle',
    'chime': 'coin pickup',
    'tick': 'click',
    'pick': 'item pickup',
    'cash': 'cash register',
    'eat': 'eating crunchy food',
    'revive': 'magic sparkle',
    'step_asphalt': 'footstep on concrete',
    'step_grass': 'footstep on grass',
    'step_wood': 'footstep on wood',
    'step_dirt': 'footstep on dirt',
    'step_run_asphalt': 'running footstep',
    'crowd_cheer': 'crowd cheering',
    'crowd_laugh': 'people laughing',
    'crowd_panic': 'people screaming',
    'crowd_applause': 'applause',
    'crowd_football_roar': 'football stadium crowd',
    'kids_laugh': 'kids laughing',
    'baby_cry': 'baby crying',
    'whistle_ref': 'referee whistle',
    'coughing': 'man coughing',
    'sneeze': 'sneeze',
    'clap_hands': 'hand clap',
    'bird_crow': 'crow',
    'bird_crow_flock': 'crows',
    'bird_magpie': 'magpie',
    'bird_dove': 'dove',
    'bird_pigeon': 'pigeon cooing',
    'bird_pigeon_flock_takeoff': 'pigeons flying away',
    'bird_sparrow': 'sparrows',
    'bird_swallow': 'swallows',
    'bird_swift': 'swifts',
    'bird_blackbird': 'blackbird',
    'bird_nightingale': 'nightingale',
    'bird_songbird_day': 'birds singing',
    'bird_tit': 'small bird',
    'bird_cuckoo': 'cuckoo',
    'bird_woodpecker': 'woodpecker',
    'bird_owl': 'owl',
    'bird_owl_little': 'small owl',
    'bird_duck': 'duck quack',
    'bird_duck_flock': 'ducks quacking',
    'bird_duck_takeoff': 'ducks flying off water',
    'bird_goose': 'geese',
    'bird_swan': 'swan',
    'bird_seagull': 'seagulls',
    'bird_heron': 'heron',
    'bird_stork_clatter': 'stork clattering',
    'bird_rooster': 'rooster',
    'bird_hen': 'chickens',
    'bird_jay': 'jay bird',
    'bird_hoopoe': 'hoopoe',
    'bird_wings_flap': 'wings flapping',
    'bird_hawk': 'hawk',
    'birds': 'birds in park',
    'amb_dawn_chorus': 'birds at dawn',
    'dog': 'dog barking',
    'dog_small': 'small dog barking',
    'dog_big': 'big dog barking',
    'dog_growl': 'dog growling',
    'dog_howl': 'dog howling',
    'dog_pack_distant': 'stray dogs barking far away',
    'cat_meow': 'cat meow',
    'cat_fight': 'cats fighting',
    'cow_bell': 'cow bells',
    'sheep_bleat': 'sheep',
    'donkey': 'donkey',
    'horse_neigh': 'horse',
    'frog_croak': 'frog',
    'rat_squeak': 'rat squeak',
    'bee_buzz': 'bee',
    'fly_buzz': 'fly buzzing',
    'crickets': 'crickets',
    'cicadas': 'cicadas',
    'frog_chorus': 'frogs at night',
    'city': 'city noise',
    'traffic': 'busy traffic',
    'amb_traffic_jam': 'traffic jam honking',
    'amb_street_quiet': 'quiet street',
    'amb_street_night': 'street at night',
    'amb_bridge_traffic': 'traffic on bridge',
    'amb_courtyard': 'apartment courtyard',
    'amb_industrial': 'factory hum',
    'amb_railway': 'railway',
    'crowd': 'crowd talking',
    'amb_cafe_terrace': 'busy cafe',
    'amb_bazaar': 'busy market',
    'amb_square_day': 'city square',
    'amb_playground': 'kids playing',
    'amb_football_pitch': 'kids playing football',
    'amb_night_party': 'party music far away',
    'amb_market_morning': 'morning market',
    'amb_wedding_distant': 'balkan wedding music far away',
    'street_musician_accordion': 'accordion music',
    'amb_park_day': 'park',
    'amb_forest_day': 'forest',
    'amb_forest_night': 'forest at night',
    'amb_meadow_day': 'meadow insects',
    'amb_hill_wind': 'wind on hill',
    'wind': 'wind',
    'amb_wind_trees': 'wind in trees',
    'wind_gust': 'wind gust',
    'fireworks_distant': 'fireworks far away',
    'amb_river_vardar': 'river',
    'amb_river_ducks': 'river with ducks',
    'amb_lake_shore': 'lake waves',
    'amb_creek': 'stream',
    'construction': 'construction site',
    'hammer': 'hammer',
    'hammer_steel': 'hammer on metal',
    'drill': 'drill',
    'jackhammer': 'jackhammer',
    'angle_grinder': 'grinder',
    'saw_wood': 'saw',
    'shovel_gravel': 'shovel in gravel',
    'metal_clank': 'metal clank',
    'truck_reverse_beep': 'truck reversing beep',
    'crane_hum': 'crane motor',
    'concrete_mixer': 'cement mixer',
    'fence_rattle': 'fence rattle',
    'wheelbarrow': 'wheelbarrow',
    'tin_roof_bang': 'metal sheet banging',
    'bell': 'church bell',
    'clock_tower': 'clock tower bell',
    'window_open': 'window opening',
    'shutter_roll': 'rolling shutter',
    'door_slam': 'door slam',
    'door_knock': 'door knock',
    'door': 'door',
    'tv_apartment': 'tv in next room',
    'laundry_flap': 'laundry flapping',
    'scooter_bell': 'bicycle bell',
    'bicycle_pass': 'bicycle',
    'sweeper_machine': 'street sweeper',
    'garbage_truck': 'garbage truck',
    'street_lamp_buzz': 'electric buzz',
    'power_transformer_hum': 'electric hum',
    'neon_buzz': 'neon buzz',
    'bullet_car_ping': 'bullet hitting metal',
    'bullet_tree': 'bullet hitting wood',
    'bullet_ground': 'bullet hitting dirt',
    'bullet_flesh': 'bullet hit',
    'hurt_thud': 'body hit',
    'defib_zap': 'electric zap',
    'fuel_warning': 'warning beeps',
    'fuel_pour': 'pouring gas',
    'engine_stall': 'car engine stalling',
    'fire_ignite': 'fire starting',
    'fire_out_hiss': 'fire hiss',
    'bus_door': 'bus door',
    'bus_air_brake': 'bus brakes hiss',
    'weapon_pickup': 'gun reload',
    'teleport_whoosh': 'whoosh',
    'map_paper': 'paper rustle',
    'denied_buzz': 'error buzz',
    'ui_click': 'click',
    'ui_confirm': 'confirm beep',
    'amb_pigeons_square': 'pigeons',
    'amb_city_far': 'distant city',
    'amb_wind_high': 'high wind',
}


def _gamify(row):
    key, folder, loop, secs, n, prompt, lvl, fb = row
    p = SIMPLE.get(key, prompt)                    # plain 1-5 word description + one short style phrase
    if loop:
        steady = folder.startswith("vehicles") or folder.startswith("construction") or key in ("street_lamp_buzz", "power_transformer_hum", "neon_buzz")    # machines hum evenly
        return (key, folder, loop, secs, n, p + (_TAIL_STEADY if steady else _TAIL_LOOP), lvl, fb)
    cap = next((c for pre, c in _CAP if key.startswith(pre)), _GROUP_CAP.get(folder, _GROUP_CAP.get(folder.split("/")[0], 2.5)))
    ring = any(key.startswith(r) for r in _RING)
    return (key, folder, loop, max(0.5, min(secs, cap)), n, p + (_TAIL_RING if ring else _TAIL_SHOT), lvl, fb)


import re as _re  # noqa: E402
CATALOG[:] = [_gamify(r) for r in CATALOG]

CATALOG[:] = [r for r in CATALOG if r]


ALIAS = {"ai_" + k: k for k in ("engine_i4", "engine_small", "engine_v8", "engine_diesel", "engine_truck", "engine_ev")}    # traffic engines: own player instance, same recording
ALIAS["engine"] = "engine_i4"
ALIAS["siren"] = "siren_police"

BY_KEY = {r[0]: r for r in CATALOG}
assert len(BY_KEY) == len(CATALOG), "duplicate sound keys"


# Random detune applied to every play of a library one-shot (+-fraction of pitch), by folder; a sound's own variations come on top of it
PITCH_VAR = {"steps": 0.08, "birds": 0.07, "animals": 0.07, "crowd": 0.06, "fight": 0.06, "impacts": 0.05, "construction": 0.06, "weapons": 0.03,
             "explosions": 0.04, "pickups": 0.03, "interface": 0.02, "vehicles/horns": 0.02, "vehicles/sirens": 0.0, "city": 0.05, "water": 0.05}


def pitch_var(row):
    f = row[1]
    return PITCH_VAR.get(f, PITCH_VAR.get(f.split("/")[0], 0.04))
