//Maya ASCII 2025ff03 scene
//Self-authored deterministic MayaScope fixture: two missing reference instances and one namespace intruder.
file -rdi 1 -ns "assetA" -rfn "assetARN" -typ "mayaAscii" "missing/reference-health-asset.ma";
file -rdi 1 -ns "assetB" -rfn "assetBRN" -typ "mayaAscii" "missing/reference-health-asset.ma";
file -r -ns "assetA" -dr 1 -rfn "assetARN" -typ "mayaAscii" "missing/reference-health-asset.ma";
file -r -ns "assetB" -dr 1 -rfn "assetBRN" -typ "mayaAscii" "missing/reference-health-asset.ma";
requires maya "2025ff03";
currentUnit -l centimeter -a degree -t film;
fileInfo "application" "maya";
fileInfo "product" "Maya 2025";
createNode transform -n "assetA:localIntruder";
