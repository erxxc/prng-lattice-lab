-- 0002_cell_ambiguity: record the recoverability outcome honestly.
-- The general solver (recover.lattice.solve_box + recover.enumerate) can resolve a
-- cell to a UNIQUE state, expose genuine collisions (>1 consistent state -- the
-- recoverability edge), or find the leak information-theoretically underdetermined.
-- These columns let a cell carry that distinction instead of collapsing every
-- non-unique result to successes=0 (rule 8: uncertainty is a range, not one number).
ALTER TABLE sweep_cell ADD COLUMN mean_candidates REAL;
ALTER TABLE sweep_cell ADD COLUMN outcome TEXT;
