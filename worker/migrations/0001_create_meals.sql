-- Migration number: 0001 	 2026-08-04T00:00:00.000Z
CREATE TABLE meals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  device_id TEXT,
  caption TEXT NOT NULL,
  detail TEXT NOT NULL,
  is_food INTEGER NOT NULL DEFAULT 0,
  food_name TEXT,
  kcal_est INTEGER,
  food_category TEXT,
  lat REAL,
  lon REAL,
  provider TEXT
);

CREATE INDEX idx_meals_created_at ON meals (created_at DESC);
