#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

const files = [
  'brian-harris-bmw-dashboard.html',
  'audi-baton-rouge-dashboard.html',
  'bmw-jackson-dashboard.html',
];

let allPassed = true;

for (const fname of files) {
  const content = fs.readFileSync(path.join(__dirname, fname), 'utf8');
  console.log(`\n${'='.repeat(55)}`);
  console.log(fname);
  console.log('='.repeat(55));

  const dataMatch = content.match(/const DATA\s*=\s*(\{[\s\S]*?\});\s*\n\s*const SOURCES/);
  if (!dataMatch) { console.log('❌ Could not extract DATA object'); allPassed = false; continue; }

  let DATA;
  try {
    DATA = eval('(' + dataMatch[1] + ')');
  } catch(e) {
    console.log('❌ DATA object parse error:', e.message);
    allPassed = false;
    continue;
  }

  const required = ['last30','last60','q1_2026','prev30','prev60','prev90','yoy30','yoy60','yoy90'];
  for (const key of required) {
    if (!DATA[key]) {
      console.log(`❌ Missing dataset: ${key}`);
      allPassed = false;
    } else if (!DATA[key].sessions) {
      console.log(`❌ ${key} has no sessions`);
      allPassed = false;
    } else {
      console.log(`✅ ${key}: sessions=${DATA[key].sessions.toLocaleString()} label="${DATA[key].label}"`);
    }
  }

  const ranges = [30, 60, 90];
  const compares = ['prev', 'yoy', 'none'];
  console.log('\n  Range+Compare matrix:');
  for (const range of ranges) {
    const curr = range === 30 ? DATA.last30 : range === 60 ? DATA.last60 : DATA.q1_2026;
    for (const compare of compares) {
      let comp = null;
      if (compare === 'yoy') comp = range === 90 ? DATA.yoy90 : range === 60 ? DATA.yoy60 : DATA.yoy30;
      else if (compare === 'prev') comp = range === 90 ? DATA.prev90 : range === 60 ? DATA.prev60 : DATA.prev30;
      const currOk = curr && curr.sessions;
      const compOk = compare === 'none' ? true : comp && comp.sessions;
      const status = currOk && compOk ? '✅' : '❌';
      if (!currOk || !compOk) allPassed = false;
      console.log(`  ${status} Last ${range} days + ${compare}: curr=${curr?.sessions?.toLocaleString() || 'NULL'} comp=${compare==='none'?'n/a':(comp?.sessions?.toLocaleString() || 'NULL')}`);
    }
  }

  console.log('\n  Daily array lengths:');
  for (const key of required) {
    const labelsLen = DATA[key]?.daily?.labels?.length || 0;
    const sessionsLen = DATA[key]?.daily?.sessions?.length || 0;
    const ok = labelsLen > 0 && labelsLen === sessionsLen;
    if (!ok) allPassed = false;
    console.log(`  ${ok?'✅':'❌'} ${key}: labels=${labelsLen} sessions=${sessionsLen}`);
  }
}

console.log('\n' + '='.repeat(55));
if (allPassed) console.log('✅ ALL CHECKS PASSED — safe to push');
else { console.log('❌ FAILURES DETECTED — do not push'); process.exit(1); }
