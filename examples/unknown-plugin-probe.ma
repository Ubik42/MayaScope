//Maya ASCII 2025 scene
//Self-authored deterministic MayaScope fixture: one deliberately missing plug-in.
requires maya "2025";
requires -nodeType "studioGhostSolver" "studioGhostTools" "4.7";
currentUnit -l centimeter -a degree -t film;
fileInfo "application" "maya";
fileInfo "product" "Maya 2025";
createNode studioGhostSolver -n "ghostSolver1";
