BEGIN TRANSACTION;
CREATE TABLE accounts (
	id INTEGER NOT NULL, 
	name VARCHAR(60) NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	kind VARCHAR(10) NOT NULL, 
	is_default BOOLEAN DEFAULT '0' NOT NULL, 
	archived BOOLEAN DEFAULT '0' NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "accounts" VALUES(1,'Main bank','EUR','bank',1,0,'2026-11-11 11:53:54.803276');
INSERT INTO "accounts" VALUES(2,'Dollar account','USD','bank',0,0,'2026-11-11 11:53:54.811436');
INSERT INTO "accounts" VALUES(3,'Cold wallet','BTC','wallet',0,0,'2026-11-11 11:53:54.816560');
INSERT INTO "accounts" VALUES(4,'Closed bank','EUR','bank',0,1,'2026-11-11 11:53:54.820439');
CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL, 
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO "alembic_version" VALUES('0011');
CREATE TABLE breaks (
	id INTEGER NOT NULL, 
	entry_date DATE NOT NULL, 
	break_minutes INTEGER NOT NULL, start_time VARCHAR(5), end_time VARCHAR(5), 
	PRIMARY KEY (id), 
	FOREIGN KEY(entry_date) REFERENCES work_entries (date) ON DELETE CASCADE
);
CREATE TABLE "freelance_blocks" (
	id INTEGER NOT NULL, 
	date DATE NOT NULL, 
	source_id INTEGER NOT NULL, 
	minutes INTEGER NOT NULL, 
	start_time VARCHAR(5), 
	end_time VARCHAR(5), 
	notes TEXT, 
	rate FLOAT NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	fx_rate FLOAT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES income_sources (id) ON DELETE RESTRICT
);
INSERT INTO "freelance_blocks" VALUES(1,'2026-01-06',3,600,NULL,NULL,NULL,75.0,'USD',NULL);
INSERT INTO "freelance_blocks" VALUES(2,'2026-03-03',1,1200,NULL,NULL,NULL,90.0,'USD',1.085);
INSERT INTO "freelance_blocks" VALUES(3,'2026-03-04',2,480,NULL,NULL,NULL,60.0,'EUR',NULL);
INSERT INTO "freelance_blocks" VALUES(4,'2026-03-10',1,1350,NULL,NULL,NULL,90.0,'USD',1.085);
INSERT INTO "freelance_blocks" VALUES(5,'2026-03-11',3,600,NULL,NULL,NULL,75.0,'USD',1.085);
INSERT INTO "freelance_blocks" VALUES(6,'2026-06-02',1,1200,NULL,NULL,NULL,90.0,'USD',1.102);
INSERT INTO "freelance_blocks" VALUES(7,'2026-06-09',1,1260,NULL,NULL,NULL,90.0,'USD',1.102);
INSERT INTO "freelance_blocks" VALUES(8,'2026-06-16',1,1140,NULL,NULL,NULL,90.0,'USD',1.102);
INSERT INTO "freelance_blocks" VALUES(9,'2026-06-23',1,1200,NULL,NULL,NULL,90.0,'USD',1.102);
INSERT INTO "freelance_blocks" VALUES(10,'2026-06-03',2,600,NULL,NULL,NULL,60.0,'EUR',NULL);
INSERT INTO "freelance_blocks" VALUES(11,'2026-06-10',2,720,NULL,NULL,NULL,60.0,'EUR',NULL);
INSERT INTO "freelance_blocks" VALUES(12,'2026-06-04',3,480,NULL,NULL,NULL,75.0,'USD',1.102);
CREATE TABLE "freelance_payouts" (
	id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	week_start DATE NOT NULL, 
	amount FLOAT NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	fx_rate FLOAT, 
	note TEXT, 
	account_id INTEGER, 
	rate_source VARCHAR(12), 
	rate_date DATE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_freelance_payouts_source_week UNIQUE (source_id, week_start), 
	CONSTRAINT fk_freelance_payouts_account_id FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT, 
	FOREIGN KEY(source_id) REFERENCES income_sources (id) ON DELETE RESTRICT
);
INSERT INTO "freelance_payouts" VALUES(1,3,'2026-01-05',750.0,'USD',NULL,NULL,NULL,NULL,NULL);
INSERT INTO "freelance_payouts" VALUES(2,1,'2026-03-02',1800.0,'USD',1.085,NULL,NULL,NULL,NULL);
INSERT INTO "freelance_payouts" VALUES(3,2,'2026-03-02',480.0,'EUR',NULL,NULL,NULL,NULL,NULL);
INSERT INTO "freelance_payouts" VALUES(4,1,'2026-03-09',2000.0,'USD',1.09,'rate typed by hand',NULL,NULL,NULL);
INSERT INTO "freelance_payouts" VALUES(5,3,'2026-03-09',700.0,'USD',1.085,NULL,NULL,NULL,NULL);
INSERT INTO "freelance_payouts" VALUES(6,1,'2026-06-01',1650.0,'EUR',NULL,NULL,1,NULL,'2026-06-07');
INSERT INTO "freelance_payouts" VALUES(7,1,'2026-06-08',1900.0,'USD',1.102,NULL,2,'ECB','2026-06-12');
INSERT INTO "freelance_payouts" VALUES(8,1,'2026-06-15',0.021,'BTC',1.235294117647058885e-05,NULL,3,'manual','2026-06-21');
INSERT INTO "freelance_payouts" VALUES(9,1,'2026-06-22',0.022,'BTC',1.234567901234567829e-05,NULL,3,'CoinGecko','2026-06-28');
INSERT INTO "freelance_payouts" VALUES(10,2,'2026-06-01',600.0,'EUR',NULL,NULL,NULL,NULL,NULL);
INSERT INTO "freelance_payouts" VALUES(11,2,'2026-06-08',700.0,'USD',1.1,NULL,2,'manual','2026-06-14');
INSERT INTO "freelance_payouts" VALUES(12,3,'2026-06-01',500.0,'EUR',NULL,NULL,4,NULL,'2026-06-07');
CREATE TABLE freelance_tax_years (
	year INTEGER NOT NULL, 
	salary_annual FLOAT NOT NULL, 
	tarifa_plana BOOLEAN DEFAULT '0' NOT NULL, 
	inicio_actividad BOOLEAN DEFAULT '0' NOT NULL, 
	set_aside_share FLOAT DEFAULT '0.4' NOT NULL, 
	gestoria_annual FLOAT DEFAULT '0' NOT NULL, 
	other_expenses FLOAT DEFAULT '0' NOT NULL, 
	PRIMARY KEY (year)
);
CREATE TABLE "income_sources" (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	hourly_rate FLOAT NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	is_default BOOLEAN DEFAULT '0' NOT NULL, 
	archived BOOLEAN DEFAULT '0' NOT NULL, 
	default_account_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT fk_income_sources_default_account_id FOREIGN KEY(default_account_id) REFERENCES accounts (id) ON DELETE SET NULL
);
INSERT INTO "income_sources" VALUES(1,'Northwind Labs',90.0,'USD',1,0,1);
INSERT INTO "income_sources" VALUES(2,'Local consulting',60.0,'EUR',0,0,NULL);
INSERT INTO "income_sources" VALUES(3,'Old client',75.0,'USD',0,1,4);
CREATE TABLE plans (
	date DATE NOT NULL, 
	day_type VARCHAR(16) NOT NULL, 
	fraction FLOAT DEFAULT '1.0' NOT NULL, 
	notes TEXT, 
	PRIMARY KEY (date)
);
CREATE TABLE settings (
	"key" VARCHAR(64) NOT NULL, 
	value VARCHAR(256) NOT NULL, 
	PRIMARY KEY ("key")
);
INSERT INTO "settings" VALUES('daily_target_hours','8.0');
INSERT INTO "settings" VALUES('cumulative_start_date','2025-01-01');
INSERT INTO "settings" VALUES('reset_annually','false');
INSERT INTO "settings" VALUES('work_week_days','0,1,2,3,4');
INSERT INTO "settings" VALUES('vacation_budget_days','0');
CREATE TABLE templates (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	start_time VARCHAR(5) NOT NULL, 
	end_time VARCHAR(5) NOT NULL, 
	breaks TEXT DEFAULT '[]' NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "templates" VALUES(1,'Office day','09:00','17:30','[]');
INSERT INTO "templates" VALUES(2,'Short Friday','08:00','14:00','[]');
CREATE TABLE work_entries (
	date DATE NOT NULL, 
	day_type VARCHAR(16) DEFAULT 'work' NOT NULL, 
	start_time VARCHAR(5), 
	end_time VARCHAR(5), 
	notes TEXT, fraction FLOAT DEFAULT '1.0' NOT NULL, 
	PRIMARY KEY (date)
);
CREATE INDEX ix_breaks_entry_date ON breaks (entry_date);
CREATE INDEX ix_freelance_blocks_source_id ON freelance_blocks (source_id);
CREATE INDEX ix_freelance_blocks_date ON freelance_blocks (date);
CREATE INDEX ix_freelance_payouts_week_start ON freelance_payouts (week_start);
CREATE INDEX ix_freelance_payouts_source_id ON freelance_payouts (source_id);
CREATE INDEX ix_freelance_payouts_account_id ON freelance_payouts (account_id);
COMMIT;
