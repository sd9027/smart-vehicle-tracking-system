-- =====================================================================
-- TrackTech fleet management: MySQL 8.0.16+ schema (InnoDB)
--
-- Run as a MySQL admin user:
--   mysql -u root -p < database/schema.sql
--
-- InnoDB gives us ACID transactions, row-level locking and foreign keys.
-- CHECK constraints are enforced from MySQL 8.0.16 onwards.
-- Keep this file in sync with backend/app/models.py.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS tracktech_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE tracktech_db;

-- Drop in reverse dependency order so the script can be re-run.
DROP TABLE IF EXISTS transaction_audit;
DROP TABLE IF EXISTS maintenance_records;
DROP TABLE IF EXISTS fuel_records;
DROP TABLE IF EXISTS expenses;
DROP TABLE IF EXISTS vehicle_locations;
DROP TABLE IF EXISTS trips;
DROP TABLE IF EXISTS vehicle_assignments;
DROP TABLE IF EXISTS drivers;
DROP TABLE IF EXISTS vehicles;
DROP TABLE IF EXISTS users;

-- ---------------------------------------------------------------------
CREATE TABLE users (
  id             INT          NOT NULL AUTO_INCREMENT,
  name           VARCHAR(100) NOT NULL,
  email          VARCHAR(255) NOT NULL,
  password_hash  VARCHAR(255) NOT NULL,             -- bcrypt hash, never the password
  role           ENUM('ADMIN','MANAGER','VIEWER') NOT NULL DEFAULT 'VIEWER',
  is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
  token_version  INT          NOT NULL DEFAULT 0,   -- bumped on password change to revoke old tokens
  created_at     DATETIME     NOT NULL,
  last_login_at  DATETIME     NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_users_email UNIQUE (email)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
CREATE TABLE vehicles (
  id               INT           NOT NULL AUTO_INCREMENT,
  registration_no  VARCHAR(15)   NOT NULL,           -- stored without spaces, e.g. UK07AB1234
  model            VARCHAR(100)  NOT NULL,
  fuel_type        ENUM('PETROL','DIESEL','CNG','ELECTRIC','HYBRID') NOT NULL,
  status           ENUM('AVAILABLE','IN_USE','MAINTENANCE','INACTIVE') NOT NULL DEFAULT 'AVAILABLE',
  odometer_km      DECIMAL(10,1) NOT NULL DEFAULT 0,
  is_demo          BOOLEAN       NOT NULL DEFAULT FALSE,  -- transaction-lab test vehicle
  version          INT           NOT NULL,           -- optimistic locking counter
  created_at       DATETIME      NOT NULL,
  updated_at       DATETIME      NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_vehicles_registration UNIQUE (registration_no),
  CONSTRAINT chk_vehicles_odometer CHECK (odometer_km >= 0),
  INDEX ix_vehicles_status (status)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
CREATE TABLE drivers (
  id              INT          NOT NULL AUTO_INCREMENT,
  name            VARCHAR(100) NOT NULL,
  license_no      VARCHAR(30)  NOT NULL,
  license_expiry  DATE         NOT NULL,
  phone           VARCHAR(20)  NOT NULL,
  status          ENUM('AVAILABLE','ON_TRIP','OFF_DUTY','INACTIVE') NOT NULL DEFAULT 'AVAILABLE',
  version         INT          NOT NULL,
  created_at      DATETIME     NOT NULL,
  updated_at      DATETIME     NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_drivers_license UNIQUE (license_no),
  INDEX ix_drivers_status (status)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Default driver for each vehicle. end_date NULL means "current".
-- The STORED generated columns hold the id only while the row is open (NULL otherwise).
-- A UNIQUE index ignores NULLs, so this enforces "one open assignment per vehicle
-- and per driver" inside the database itself (MySQL has no partial indexes).
CREATE TABLE vehicle_assignments (
  id               INT      NOT NULL AUTO_INCREMENT,
  vehicle_id       INT      NOT NULL,
  driver_id        INT      NOT NULL,
  start_date       DATETIME NOT NULL,
  end_date         DATETIME NULL,
  open_vehicle_id  INT GENERATED ALWAYS AS (CASE WHEN end_date IS NULL THEN vehicle_id ELSE NULL END) STORED,
  open_driver_id   INT GENERATED ALWAYS AS (CASE WHEN end_date IS NULL THEN driver_id  ELSE NULL END) STORED,
  PRIMARY KEY (id),
  CONSTRAINT fk_assign_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles (id),
  CONSTRAINT fk_assign_driver  FOREIGN KEY (driver_id)  REFERENCES drivers (id),
  CONSTRAINT uq_assign_open_vehicle UNIQUE (open_vehicle_id),
  CONSTRAINT uq_assign_open_driver  UNIQUE (open_driver_id),
  CONSTRAINT chk_assign_dates CHECK (end_date IS NULL OR end_date >= start_date)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Same generated-column technique: a vehicle or driver can be in at most ONE
-- scheduled/active trip. This is the last line of defence against double booking.
CREATE TABLE trips (
  id               INT           NOT NULL AUTO_INCREMENT,
  vehicle_id       INT           NOT NULL,
  driver_id        INT           NOT NULL,
  source           VARCHAR(120)  NOT NULL,
  destination      VARCHAR(120)  NOT NULL,
  source_lat       DOUBLE        NOT NULL,
  source_lng       DOUBLE        NOT NULL,
  dest_lat         DOUBLE        NOT NULL,
  dest_lng         DOUBLE        NOT NULL,
  status           ENUM('SCHEDULED','ACTIVE','COMPLETED','CANCELLED') NOT NULL DEFAULT 'SCHEDULED',
  notes            VARCHAR(500)  NULL,
  created_by       INT           NULL,
  created_at       DATETIME      NOT NULL,
  start_time       DATETIME      NULL,
  end_time         DATETIME      NULL,
  distance_km      DECIMAL(10,2) NULL,
  open_vehicle_id  INT GENERATED ALWAYS AS
                   (CASE WHEN status IN ('SCHEDULED','ACTIVE') THEN vehicle_id ELSE NULL END) STORED,
  open_driver_id   INT GENERATED ALWAYS AS
                   (CASE WHEN status IN ('SCHEDULED','ACTIVE') THEN driver_id ELSE NULL END) STORED,
  PRIMARY KEY (id),
  CONSTRAINT fk_trips_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles (id),
  CONSTRAINT fk_trips_driver  FOREIGN KEY (driver_id)  REFERENCES drivers (id),
  CONSTRAINT fk_trips_creator FOREIGN KEY (created_by) REFERENCES users (id),
  CONSTRAINT uq_trips_open_vehicle UNIQUE (open_vehicle_id),
  CONSTRAINT uq_trips_open_driver  UNIQUE (open_driver_id),
  CONSTRAINT chk_trips_time_order CHECK (end_time IS NULL OR start_time IS NULL OR end_time >= start_time),
  CONSTRAINT chk_trips_distance CHECK (distance_km IS NULL OR distance_km >= 0),
  INDEX ix_trips_status (status)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
CREATE TABLE vehicle_locations (
  id            BIGINT   NOT NULL AUTO_INCREMENT,
  vehicle_id    INT      NOT NULL,
  trip_id       INT      NULL,
  latitude      DOUBLE   NOT NULL,
  longitude     DOUBLE   NOT NULL,
  speed_kmh     DOUBLE   NOT NULL DEFAULT 0,
  is_simulated  BOOLEAN  NOT NULL DEFAULT TRUE,     -- FALSE only for real GPS hardware
  recorded_at   DATETIME NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT fk_loc_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles (id),
  CONSTRAINT fk_loc_trip    FOREIGN KEY (trip_id)    REFERENCES trips (id),
  CONSTRAINT chk_loc_lat   CHECK (latitude BETWEEN -90 AND 90),
  CONSTRAINT chk_loc_lng   CHECK (longitude BETWEEN -180 AND 180),
  CONSTRAINT chk_loc_speed CHECK (speed_kmh >= 0),
  INDEX ix_locations_vehicle_time (vehicle_id, recorded_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
CREATE TABLE expenses (
  id            INT           NOT NULL AUTO_INCREMENT,
  vehicle_id    INT           NOT NULL,
  category      ENUM('FUEL','MAINTENANCE','TOLL','INSURANCE','PARKING','OTHER') NOT NULL,
  amount        DECIMAL(10,2) NOT NULL,
  expense_date  DATE          NOT NULL,
  description   VARCHAR(255)  NOT NULL DEFAULT '',
  created_by    INT           NULL,
  created_at    DATETIME      NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT fk_exp_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles (id),
  CONSTRAINT fk_exp_creator FOREIGN KEY (created_by) REFERENCES users (id),
  CONSTRAINT chk_expenses_amount CHECK (amount >= 0),
  INDEX ix_expenses_date (expense_date)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Every fuel purchase owns exactly one expense row (1:1 via UNIQUE expense_id).
CREATE TABLE fuel_records (
  id           INT           NOT NULL AUTO_INCREMENT,
  vehicle_id   INT           NOT NULL,
  expense_id   INT           NOT NULL,
  quantity_l   DECIMAL(8,2)  NOT NULL,
  price_per_l  DECIMAL(8,2)  NOT NULL,
  total_cost   DECIMAL(10,2) NOT NULL,
  odometer_km  DECIMAL(10,1) NOT NULL,
  station      VARCHAR(120)  NULL,
  recorded_at  DATETIME      NOT NULL,
  created_by   INT           NULL,
  PRIMARY KEY (id),
  CONSTRAINT fk_fuel_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles (id),
  CONSTRAINT fk_fuel_expense FOREIGN KEY (expense_id) REFERENCES expenses (id),
  CONSTRAINT fk_fuel_creator FOREIGN KEY (created_by) REFERENCES users (id),
  CONSTRAINT uq_fuel_expense UNIQUE (expense_id),
  CONSTRAINT chk_fuel_quantity CHECK (quantity_l > 0),
  CONSTRAINT chk_fuel_price    CHECK (price_per_l > 0),
  CONSTRAINT chk_fuel_total    CHECK (total_cost >= 0),
  CONSTRAINT chk_fuel_odometer CHECK (odometer_km >= 0)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
CREATE TABLE maintenance_records (
  id                 INT           NOT NULL AUTO_INCREMENT,
  vehicle_id         INT           NOT NULL,
  expense_id         INT           NOT NULL,
  service_type       VARCHAR(60)   NOT NULL,
  description        VARCHAR(500)  NOT NULL DEFAULT '',
  service_date       DATE          NOT NULL,
  cost               DECIMAL(10,2) NOT NULL,
  odometer_km        DECIMAL(10,1) NULL,
  next_service_date  DATE          NULL,
  created_by         INT           NULL,
  created_at         DATETIME      NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT fk_maint_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles (id),
  CONSTRAINT fk_maint_expense FOREIGN KEY (expense_id) REFERENCES expenses (id),
  CONSTRAINT fk_maint_creator FOREIGN KEY (created_by) REFERENCES users (id),
  CONSTRAINT uq_maintenance_expense UNIQUE (expense_id),
  CONSTRAINT chk_maint_cost CHECK (cost >= 0),
  CONSTRAINT chk_maint_next_date CHECK (next_service_date IS NULL OR next_service_date >= service_date)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- One row per write operation, committed or rolled back. No passwords or tokens.
CREATE TABLE transaction_audit (
  id           BIGINT       NOT NULL AUTO_INCREMENT,
  user_id      INT          NULL,
  operation    VARCHAR(60)  NOT NULL,
  status       ENUM('COMMITTED','ROLLED_BACK') NOT NULL,
  entity       VARCHAR(40)  NULL,
  entity_id    INT          NULL,
  message      VARCHAR(500) NOT NULL DEFAULT '',
  details      TEXT         NULL,
  duration_ms  INT          NULL,
  created_at   DATETIME     NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES users (id),
  INDEX ix_audit_created (created_at),
  INDEX ix_audit_status (status)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Application account with only the privileges the API needs (no DROP, no GRANT).
-- Replace the password before running, and put the same value in backend/.env.
-- CREATE USER IF NOT EXISTS 'tracktech_app'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON tracktech_db.* TO 'tracktech_app'@'localhost';
-- FLUSH PRIVILEGES;
