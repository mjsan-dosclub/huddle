import test from 'node:test';
import assert from 'node:assert/strict';
import {localStamp,followUpEpoch,pickerLabel} from '../static/sales-date-picker.js';

test('follow-up wall time survives saving and reopening in the staff timezone',()=>{
 const previous=process.env.TZ;process.env.TZ='Asia/Kolkata';
 try{const selected='2026-10-26T15:25';const epoch=followUpEpoch(selected);assert.equal(localStamp(epoch),selected);assert.equal(pickerLabel(selected,true),'26 Oct 2026 · 3:25 PM');}
 finally{process.env.TZ=previous;}
});

test('invalid calendar time cannot silently move a promised follow-up',()=>{
 const previous=process.env.TZ;process.env.TZ='America/New_York';
 try{assert.equal(followUpEpoch('2026-03-08T02:30'),null);assert.equal(followUpEpoch('2026-02-30T10:00'),null);assert.equal(followUpEpoch(''),null);}
 finally{process.env.TZ=previous;}
});
