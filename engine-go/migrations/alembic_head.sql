BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001

CREATE TABLE advisors (
    id VARCHAR(36) NOT NULL, 
    firm_name VARCHAR(200) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    email VARCHAR(200) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_advisors_advisor_id ON advisors (advisor_id);

CREATE TABLE households (
    name VARCHAR(200) NOT NULL, 
    filing_status VARCHAR(8) NOT NULL, 
    state VARCHAR(2) NOT NULL, 
    tax_year_latest INTEGER NOT NULL, 
    wages_cents BIGINT NOT NULL, 
    other_income_cents BIGINT NOT NULL, 
    magi_cents BIGINT NOT NULL, 
    active_participation BOOLEAN NOT NULL, 
    re_professional BOOLEAN NOT NULL, 
    net_worth_cents BIGINT, 
    goal TEXT NOT NULL, 
    notes TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(advisor_id) REFERENCES advisors (id) ON DELETE CASCADE
);

CREATE INDEX ix_households_advisor_id ON households (advisor_id);

CREATE TABLE documents (
    household_id VARCHAR(36) NOT NULL, 
    kind VARCHAR(24) NOT NULL, 
    tax_year INTEGER, 
    filename VARCHAR(300) NOT NULL, 
    sha256 VARCHAR(64) NOT NULL, 
    page_count INTEGER NOT NULL, 
    uploaded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    bytes_retained BOOLEAN NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(advisor_id) REFERENCES advisors (id) ON DELETE CASCADE, 
    FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE
);

CREATE INDEX ix_documents_advisor_id ON documents (advisor_id);

CREATE INDEX ix_documents_household_id ON documents (household_id);

CREATE INDEX ix_documents_sha256 ON documents (sha256);

CREATE TABLE properties (
    household_id VARCHAR(36) NOT NULL, 
    nickname VARCHAR(200) NOT NULL, 
    address_line1 VARCHAR(200) NOT NULL, 
    city VARCHAR(100) NOT NULL, 
    state VARCHAR(2) NOT NULL, 
    zip VARCHAR(10) NOT NULL, 
    property_type VARCHAR(20) NOT NULL, 
    units INTEGER NOT NULL, 
    purchase_date DATE, 
    purchase_price_cents BIGINT NOT NULL, 
    placed_in_service_date DATE, 
    land_pct NUMERIC(9, 6), 
    improvements_cents BIGINT NOT NULL, 
    cost_seg_study BOOLEAN NOT NULL, 
    current_value_cents BIGINT NOT NULL, 
    value_source VARCHAR(12) NOT NULL, 
    value_as_of DATE, 
    appreciation_rate NUMERIC(9, 6), 
    rent_growth_rate NUMERIC(9, 6), 
    expense_growth_rate NUMERIC(9, 6), 
    vacancy_rate NUMERIC(9, 6), 
    mgmt_fee_rate NUMERIC(9, 6), 
    capex_reserve_rate NUMERIC(9, 6), 
    selling_cost_rate NUMERIC(9, 6), 
    status VARCHAR(12) NOT NULL, 
    former_residence_until DATE, 
    avg_stay_days FLOAT, 
    property_key VARCHAR(300), 
    id VARCHAR(36) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(advisor_id) REFERENCES advisors (id) ON DELETE CASCADE, 
    FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE
);

CREATE INDEX ix_properties_advisor_id ON properties (advisor_id);

CREATE INDEX ix_properties_household_id ON properties (household_id);

CREATE INDEX ix_properties_property_key ON properties (property_key);

CREATE TABLE suspended_losses (
    household_id VARCHAR(36) NOT NULL, 
    tax_year INTEGER NOT NULL, 
    carryforward_cents BIGINT NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(advisor_id) REFERENCES advisors (id) ON DELETE CASCADE, 
    FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    UNIQUE (household_id, tax_year)
);

CREATE INDEX ix_suspended_losses_advisor_id ON suspended_losses (advisor_id);

CREATE INDEX ix_suspended_losses_household_id ON suspended_losses (household_id);

CREATE TABLE alerts (
    household_id VARCHAR(36) NOT NULL, 
    property_id VARCHAR(36), 
    kind VARCHAR(24) NOT NULL, 
    due_date DATE, 
    message TEXT NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(advisor_id) REFERENCES advisors (id) ON DELETE CASCADE, 
    FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    FOREIGN KEY(property_id) REFERENCES properties (id) ON DELETE CASCADE
);

CREATE INDEX ix_alerts_advisor_id ON alerts (advisor_id);

CREATE INDEX ix_alerts_household_id ON alerts (household_id);

CREATE TABLE depreciation_ledgers (
    property_id VARCHAR(36) NOT NULL, 
    tax_year INTEGER NOT NULL, 
    allowed_cents BIGINT NOT NULL, 
    allowable_cents BIGINT, 
    method VARCHAR(10) NOT NULL, 
    note TEXT NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(advisor_id) REFERENCES advisors (id) ON DELETE CASCADE, 
    FOREIGN KEY(property_id) REFERENCES properties (id) ON DELETE CASCADE, 
    UNIQUE (property_id, tax_year)
);

CREATE INDEX ix_depreciation_ledgers_advisor_id ON depreciation_ledgers (advisor_id);

CREATE INDEX ix_depreciation_ledgers_property_id ON depreciation_ledgers (property_id);

CREATE TABLE expense_years (
    property_id VARCHAR(36) NOT NULL, 
    tax_year INTEGER NOT NULL, 
    taxes_cents BIGINT NOT NULL, 
    insurance_cents BIGINT NOT NULL, 
    repairs_cents BIGINT NOT NULL, 
    mgmt_cents BIGINT NOT NULL, 
    utilities_cents BIGINT NOT NULL, 
    hoa_cents BIGINT NOT NULL, 
    other_cents BIGINT NOT NULL, 
    mortgage_interest_cents BIGINT NOT NULL, 
    depreciation_cents BIGINT NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(advisor_id) REFERENCES advisors (id) ON DELETE CASCADE, 
    FOREIGN KEY(property_id) REFERENCES properties (id) ON DELETE CASCADE, 
    UNIQUE (property_id, tax_year)
);

CREATE INDEX ix_expense_years_advisor_id ON expense_years (advisor_id);

CREATE INDEX ix_expense_years_property_id ON expense_years (property_id);

CREATE TABLE extracted_fields (
    document_id VARCHAR(36) NOT NULL, 
    entity_hint VARCHAR(12) NOT NULL, 
    property_key VARCHAR(300), 
    field VARCHAR(120) NOT NULL, 
    value JSONB, 
    unit VARCHAR(8) NOT NULL, 
    page INTEGER NOT NULL, 
    bbox JSONB NOT NULL, 
    confidence FLOAT NOT NULL, 
    extractor VARCHAR(8) NOT NULL, 
    raw_text TEXT NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(advisor_id) REFERENCES advisors (id) ON DELETE CASCADE, 
    FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE INDEX ix_extracted_fields_advisor_id ON extracted_fields (advisor_id);

CREATE INDEX ix_extracted_fields_document_id ON extracted_fields (document_id);

CREATE TABLE findings (
    household_id VARCHAR(36) NOT NULL, 
    property_id VARCHAR(36), 
    key VARCHAR(200), 
    tax_year INTEGER, 
    kind VARCHAR(24) NOT NULL, 
    field VARCHAR(120) NOT NULL, 
    severity VARCHAR(8) NOT NULL, 
    message TEXT NOT NULL, 
    candidates JSONB NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    resolution JSONB, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(advisor_id) REFERENCES advisors (id) ON DELETE CASCADE, 
    FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    FOREIGN KEY(property_id) REFERENCES properties (id) ON DELETE CASCADE
);

CREATE INDEX ix_findings_advisor_id ON findings (advisor_id);

CREATE INDEX ix_findings_household_id ON findings (household_id);

CREATE TABLE loans (
    property_id VARCHAR(36) NOT NULL, 
    lender VARCHAR(200) NOT NULL, 
    loan_type VARCHAR(16) NOT NULL, 
    original_cents BIGINT NOT NULL, 
    balance_cents BIGINT NOT NULL, 
    balance_as_of DATE NOT NULL, 
    rate NUMERIC(9, 6) NOT NULL, 
    term_months INTEGER NOT NULL, 
    io_months INTEGER NOT NULL, 
    arm_reset_date DATE, 
    arm_index_margin NUMERIC(9, 6), 
    monthly_payment_cents BIGINT, 
    maturity_date DATE, 
    lien_position INTEGER NOT NULL, 
    is_paid_off BOOLEAN NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(advisor_id) REFERENCES advisors (id) ON DELETE CASCADE, 
    FOREIGN KEY(property_id) REFERENCES properties (id) ON DELETE CASCADE
);

CREATE INDEX ix_loans_advisor_id ON loans (advisor_id);

CREATE INDEX ix_loans_property_id ON loans (property_id);

CREATE TABLE rent_rolls (
    property_id VARCHAR(36) NOT NULL, 
    tax_year INTEGER NOT NULL, 
    gross_rent_cents BIGINT NOT NULL, 
    other_income_cents BIGINT NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(advisor_id) REFERENCES advisors (id) ON DELETE CASCADE, 
    FOREIGN KEY(property_id) REFERENCES properties (id) ON DELETE CASCADE, 
    UNIQUE (property_id, tax_year)
);

CREATE INDEX ix_rent_rolls_advisor_id ON rent_rolls (advisor_id);

CREATE INDEX ix_rent_rolls_property_id ON rent_rolls (property_id);

CREATE TABLE scenarios (
    property_id VARCHAR(36) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    horizon_years INTEGER NOT NULL, 
    assumptions JSONB NOT NULL, 
    results JSONB, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    advisor_id VARCHAR(36) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(advisor_id) REFERENCES advisors (id) ON DELETE CASCADE, 
    FOREIGN KEY(property_id) REFERENCES properties (id) ON DELETE CASCADE
);

CREATE INDEX ix_scenarios_advisor_id ON scenarios (advisor_id);

CREATE INDEX ix_scenarios_property_id ON scenarios (property_id);

INSERT INTO alembic_version (version_num) VALUES ('0001') RETURNING alembic_version.version_num;

-- Running upgrade 0001 -> 0002

ALTER TABLE advisors ADD COLUMN created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL;

ALTER TABLE advisors ADD COLUMN last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL;

ALTER TABLE advisors ADD COLUMN created_ip VARCHAR(64);

CREATE INDEX ix_advisors_last_seen_at ON advisors (last_seen_at);

CREATE TABLE workspace_provisions (
    ip VARCHAR(64) NOT NULL, 
    day DATE NOT NULL, 
    count INTEGER DEFAULT '0' NOT NULL, 
    PRIMARY KEY (ip, day)
);

UPDATE alembic_version SET version_num='0002' WHERE alembic_version.version_num = '0001';

COMMIT;

