// Minimal ini editing that keeps every other line exactly as it was (comments, order, CRLF).

function iniGet(text, section, key) {
  let cur = null;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    const m = line.match(/^\[(.+)\]$/);
    if (m) { cur = m[1].toLowerCase(); continue; }
    if (cur !== section.toLowerCase()) continue;
    const eq = line.indexOf('=');
    if (eq > 0 && line.slice(0, eq).trim().toLowerCase() === key.toLowerCase()) return line.slice(eq + 1).trim();
  }
  return null;
}

// value === null removes the key; a missing key is added at the end of its section (or a new section at the end)
function iniSet(text, section, key, value) {
  const eol = text.includes('\r\n') ? '\r\n' : '\n';
  const lines = text.length ? text.split(/\r?\n/) : [];
  const want = section.toLowerCase();
  let cur = null, secStart = -1, secEnd = -1, hit = -1;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    const m = line.match(/^\[(.+)\]$/);
    if (m) {
      if (cur === want && secEnd < 0) secEnd = i;
      cur = m[1].toLowerCase();
      if (cur === want && secStart < 0) secStart = i;
      continue;
    }
    if (cur !== want) continue;
    const eq = line.indexOf('=');
    if (eq > 0 && line.slice(0, eq).trim().toLowerCase() === key.toLowerCase()) hit = i;
  }
  if (secStart >= 0 && secEnd < 0) secEnd = lines.length;
  if (value === null) {
    if (hit >= 0) lines.splice(hit, 1);
  } else if (hit >= 0) {
    const old = lines[hit];
    lines[hit] = old.slice(0, old.indexOf('=')).trimEnd() + '=' + value;
  } else if (secStart >= 0) {
    let at = secEnd;
    while (at - 1 > secStart && lines[at - 1].trim() === '') at--;
    lines.splice(at, 0, key + '=' + value);
  } else {
    while (lines.length && lines[lines.length - 1] === '') lines.pop();
    if (lines.length) lines.push('');
    lines.push('[' + section + ']', key + '=' + value, '');
  }
  return lines.join(eol);
}

module.exports = { iniGet, iniSet };
