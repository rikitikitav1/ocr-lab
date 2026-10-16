-- migrate:up
-- the tree level a run's pieces were cut at, frozen when the run starts; null reads by part and chapter
ALTER TABLE runs ADD COLUMN reading_level int;
UPDATE jobs SET type = 'structure' WHERE type = 'toc';
UPDATE jobs SET type = 'structure_scan' WHERE type = 'toc_scan';
UPDATE jobs SET type = 'structure_eval' WHERE type = 'toc_eval';

-- migrate:down
UPDATE jobs SET type = 'toc_eval' WHERE type = 'structure_eval';
UPDATE jobs SET type = 'toc_scan' WHERE type = 'structure_scan';
UPDATE jobs SET type = 'toc' WHERE type = 'structure';
ALTER TABLE runs DROP COLUMN reading_level;
