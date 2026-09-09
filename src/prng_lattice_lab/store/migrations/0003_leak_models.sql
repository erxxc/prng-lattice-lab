-- 0003_leak_models: cells become self-describing about WHICH leak they observed.
-- The residue (nextInt odd) and bit-length recoveries carry a different amount of
-- information per call than bits_per_call suggests, so the realized leaked_bits is
-- stored explicitly and drives the underdetermined/edge classification (rule 8:
-- classify on the information actually present, never on a proxy).
ALTER TABLE sweep_cell ADD COLUMN model TEXT;
ALTER TABLE sweep_cell ADD COLUMN bound INTEGER;
ALTER TABLE sweep_cell ADD COLUMN leaked_bits REAL;
