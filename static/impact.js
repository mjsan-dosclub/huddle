// A transparent scenario, not measured environmental savings or a lifecycle model.
export function estimateImpact(people,cardsPerYear,plasticReplacementsPerYear){
  const clamp=(v,max)=>Math.min(max,Math.max(0,Number.isFinite(Number(v))?Number(v):0));
  const count=clamp(people,1000),cards=count*clamp(cardsPerYear,1000);
  const paperKg=cards*.085*.055*350/1000;
  return {cards,paperKg,treeEquivalent:paperKg*24/1000,plasticReplacements:count*clamp(plasticReplacementsPerYear,5)};
}
