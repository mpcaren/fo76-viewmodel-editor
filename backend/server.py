"""Line-delimited JSON request loop for the Electron app.
stdin:  {"id": n, "cmd": "...", "args": {...}}
stdout: {"id": n, "ok": true, "result": ...} | {"id": n, "ok": false, "error": "..."} | {"id": n, "progress": {...}}"""
import sys, os, json, traceback, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vmcore  # noqa: E402

out_lock = threading.Lock()


def send(obj):
    line = json.dumps(obj, separators=(',', ':'))
    with out_lock:
        sys.stdout.write(line + '\n')
        sys.stdout.flush()


def handle(req):
    cmd, a = req['cmd'], req.get('args') or {}
    if cmd == 'init':
        vmcore.index()
        vmcore.catalog()
        return {'groups': vmcore.groups(), 'data': vmcore.DATA}
    if cmd == 'scene':
        # one file per request so a second request can't overwrite it before the app reads it
        path = os.path.join(vmcore.CACHE, 'scene-%s.json' % req['id'])
        s = vmcore.pipboy_scene() if a['id'] == 'pipboy' else vmcore.scene(a['id'], a.get('parts'))
        json.dump(s, open(path, 'w'), separators=(',', ':'))
        return {'file': path}                     # big: the app reads it from disk
    if cmd == 'build':
        return vmcore.build(a['offsets'], a['out'], lambda p: send({'id': req['id'], 'progress': p}))
    if cmd == 'ping':
        return 'pong'
    raise ValueError('unknown command ' + cmd)


def main():
    send({'ready': True})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        try:
            send({'id': req['id'], 'ok': True, 'result': handle(req)})
        except Exception as e:
            send({'id': req.get('id'), 'ok': False, 'error': '%s: %s' % (type(e).__name__, e),
                  'trace': traceback.format_exc()[-2000:]})


if __name__ == '__main__':
    main()
