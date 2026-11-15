BEGIN TRANSACTION;
CREATE TABLE accounts (
	id INTEGER NOT NULL, 
	name VARCHAR(60) NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	kind VARCHAR(10) NOT NULL, 
	is_default BOOLEAN DEFAULT '0' NOT NULL, 
	archived BOOLEAN DEFAULT '0' NOT NULL, 
	created_at DATETIME NOT NULL, role VARCHAR(12) DEFAULT 'both' NOT NULL, position INTEGER DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "accounts" VALUES(1,'Stripe','USD','bank',0,0,'2026-11-01 10:00:00','origin',1);
INSERT INTO "accounts" VALUES(2,'Main bank','EUR','bank',1,0,'2026-11-01 10:00:00','destination',0);
INSERT INTO "accounts" VALUES(3,'Wise','EUR','bank',0,0,'2026-11-01 10:00:00','both',2);
INSERT INTO "accounts" VALUES(4,'Old pot','EUR','bank',0,1,'2026-11-01 10:00:00','both',3);
CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL, 
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO "alembic_version" VALUES('0013');
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
CREATE TABLE freelance_payout_legs (
	id INTEGER NOT NULL, 
	payout_id INTEGER NOT NULL, 
	position INTEGER NOT NULL, 
	account_id INTEGER NOT NULL, 
	amount FLOAT NOT NULL, 
	fixed BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_freelance_payout_legs_position UNIQUE (payout_id, position), 
	CONSTRAINT uq_freelance_payout_legs_account UNIQUE (payout_id, account_id), 
	CONSTRAINT ck_freelance_payout_legs_position CHECK (position BETWEEN 0 AND 3), 
	FOREIGN KEY(payout_id) REFERENCES freelance_payouts (id) ON DELETE CASCADE, 
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT
);
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
	sent_amount FLOAT, 
	sent_currency VARCHAR(8), 
	from_account_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_freelance_payouts_source_week UNIQUE (source_id, week_start), 
	CONSTRAINT fk_freelance_payouts_account_id FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_freelance_payouts_from_account_id FOREIGN KEY(from_account_id) REFERENCES accounts (id) ON DELETE RESTRICT, 
	FOREIGN KEY(source_id) REFERENCES income_sources (id) ON DELETE RESTRICT
);
INSERT INTO "freelance_payouts" VALUES(1,1,'2026-10-05',1900.0,'USD',1.1165,'no account',NULL,'manual','2026-10-11',NULL,NULL,NULL);
INSERT INTO "freelance_payouts" VALUES(2,1,'2026-10-12',894.76,'EUR',NULL,NULL,2,NULL,'2026-10-18',999.0,'USD',NULL);
INSERT INTO "freelance_payouts" VALUES(3,2,'2026-10-12',900.0,'EUR',NULL,NULL,3,NULL,'2026-10-18',900.0,'EUR',3);
INSERT INTO "freelance_payouts" VALUES(4,1,'2026-10-19',894.76,'EUR',NULL,NULL,2,NULL,'2026-10-25',999.0,'USD',1);
INSERT INTO "freelance_payouts" VALUES(5,2,'2026-10-19',450.0,'EUR',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO "freelance_payouts" VALUES(6,5,'2026-10-26',300.0,'EUR',NULL,NULL,3,NULL,'2026-11-01',NULL,NULL,NULL);
INSERT INTO "freelance_payouts" VALUES(7,1,'2026-11-02',1000.0,'USD',NULL,NULL,2,NULL,NULL,NULL,NULL,NULL);
INSERT INTO "freelance_payouts" VALUES(8,1,'2026-11-09',880.0,'EUR',NULL,NULL,2,NULL,'2026-11-15',990.0,NULL,NULL);
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
CREATE TABLE income_source_accounts (
	id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	position INTEGER NOT NULL, 
	account_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_income_source_accounts_position UNIQUE (source_id, position), 
	CONSTRAINT uq_income_source_accounts_account UNIQUE (source_id, account_id), 
	CONSTRAINT ck_income_source_accounts_position CHECK (position BETWEEN 0 AND 3), 
	FOREIGN KEY(source_id) REFERENCES income_sources (id) ON DELETE CASCADE, 
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE
);
CREATE TABLE "income_sources" (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	hourly_rate FLOAT NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	is_default BOOLEAN DEFAULT '0' NOT NULL, 
	archived BOOLEAN DEFAULT '0' NOT NULL, 
	default_account_id INTEGER, 
	default_from_account_id INTEGER, position INTEGER DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT fk_income_sources_default_account_id FOREIGN KEY(default_account_id) REFERENCES accounts (id) ON DELETE SET NULL, 
	CONSTRAINT fk_income_sources_default_from_account_id FOREIGN KEY(default_from_account_id) REFERENCES accounts (id) ON DELETE RESTRICT
);
INSERT INTO "income_sources" VALUES(1,'Northwind',90.0,'USD',1,0,2,1,0);
INSERT INTO "income_sources" VALUES(2,'Local',60.0,'EUR',0,0,3,NULL,1);
INSERT INTO "income_sources" VALUES(3,'Same',60.0,'EUR',0,0,3,3,2);
INSERT INTO "income_sources" VALUES(4,'Shelved',50.0,'USD',0,0,4,NULL,3);
INSERT INTO "income_sources" VALUES(5,'Plain',40.0,'EUR',0,0,NULL,NULL,4);
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
	breaks TEXT DEFAULT '[]' NOT NULL, position INTEGER DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id)
);
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
CREATE INDEX ix_freelance_payouts_source_id ON freelance_payouts (source_id);
CREATE INDEX ix_freelance_payouts_account_id ON freelance_payouts (account_id);
CREATE INDEX ix_freelance_payouts_week_start ON freelance_payouts (week_start);
CREATE INDEX ix_freelance_payouts_from_account_id ON freelance_payouts (from_account_id);
CREATE INDEX ix_freelance_payout_legs_payout_id ON freelance_payout_legs (payout_id);
CREATE INDEX ix_freelance_payout_legs_account_id ON freelance_payout_legs (account_id);
CREATE INDEX ix_income_source_accounts_source_id ON income_source_accounts (source_id);
CREATE INDEX ix_income_source_accounts_account_id ON income_source_accounts (account_id);
COMMIT;
