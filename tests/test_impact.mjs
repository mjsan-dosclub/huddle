import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../static/impact.js',import.meta.url),'utf8');
const {estimateImpact}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('paper weight uses card area and GSM, then converts kg to a disclosed tree equivalent',()=>{const r=estimateImpact(50,200,1);assert.equal(r.cards,10000);assert.ok(Math.abs(r.paperKg-16.3625)<1e-8);assert.ok(Math.abs(r.treeEquivalent-.3927)<1e-8);assert.equal(r.plasticReplacements,50);});
test('digital-only and zero-use cases do not claim NFC or paper savings',()=>{assert.equal(estimateImpact(50,200,0).plasticReplacements,0);assert.equal(estimateImpact(50,0,1).treeEquivalent,0);assert.equal(estimateImpact(0,200,1).cards,0);});
test('invalid and negative values cannot inflate the scenario',()=>{assert.equal(estimateImpact(NaN,-4,Infinity).treeEquivalent,0);assert.equal(estimateImpact(5000,5000,10).cards,1000000);});
