import sys, json
for l in sys.stdin:
    try: d = json.loads(l)
    except ValueError: print(l.strip()[:300]); continue
    print(d['role'], d['state'], 'NAT', d['nat'], repr(d['error']), d['log'][-1], 'chat', len(d['chat']), 'rx', d['voice_rx_frames'], 'loss', d['loss'], 'fec', d['fec_fixed'], d['tier'], '(' + d['why'] + ')', '|', d['hear'], '|', d['them'])
