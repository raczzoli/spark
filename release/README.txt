R89 Repairs - EC / Battery tools 0.4.0
GUI: b665d6bbde8a | firmware unchanged: bf378ee841d8

Run app/EC-Programmer.exe. Automatic USB discovery is shared by both EC and battery workspaces.
Interface bar above the EC/Battery tabs: detected COM + board model + Connected. No COM selector or Refresh. Battery header: empty model search + Read and pinout; model selection is not persisted.
General info: automatic controller identification, battery lockout status, measured cells, identity and capacities.
Measurements: graph and Live readings. Controller: identity, operation and checks; settings and raw data under Advanced.
Action feedback remains visible; there is no battery log panel.
Unknown operating/cell data stays unknown. Seal/Unseal is separate from battery lockout. Cell comparison uses an explicit 50 mV display reference.
TI bq40z50-R3 service/PF recovery is experimental and needs the battery's own keys. ID 4555 remains diagnostics-only.
Pico is detected at startup and on USB arrival/removal. Supplied UF2s are unchanged.
See Battery-Guide.md for setup and validation limits.
