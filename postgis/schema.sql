-- PostGIS schema for the zero-dose early-warning system
-- Load districts:  ogr2ogr -f PostgreSQL PG:"dbname=ews" data/uganda_districts.geojson -nln admin.districts -lco GEOMETRY_NAME=geom
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS admin;
CREATE SCHEMA IF NOT EXISTS health;

CREATE TABLE IF NOT EXISTS admin.districts (
    district_code text PRIMARY KEY,
    district      text NOT NULL,
    region        text,
    geom          geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS districts_geom_gix ON admin.districts USING gist (geom);

CREATE TABLE IF NOT EXISTS health.immunisation_monthly (
    district_code text REFERENCES admin.districts,
    period        date NOT NULL,              -- first day of reporting month
    target_under1 integer NOT NULL,
    penta1        integer NOT NULL,
    penta3        integer NOT NULL,
    mcv1          integer NOT NULL,
    PRIMARY KEY (district_code, period),
    CHECK (penta3 <= penta1)                  -- integrity check: dose 3 cannot exceed dose 1
);

-- Indicators with rolling windows
CREATE OR REPLACE VIEW health.v_zero_dose AS
SELECT district_code, period,
       penta1::numeric / NULLIF(target_under1, 0)                                         AS penta1_cov,
       1 - penta3::numeric / NULLIF(penta1, 0)                                             AS dropout_p1_p3,
       AVG(penta1::numeric / NULLIF(target_under1, 0))
           OVER (PARTITION BY district_code ORDER BY period ROWS 2 PRECEDING)             AS penta1_cov_3m,
       SUM(GREATEST(target_under1 - penta1, 0))
           OVER (PARTITION BY district_code ORDER BY period ROWS 11 PRECEDING)            AS zero_dose_12m
FROM health.immunisation_monthly;

-- Threshold-based warning level for the latest month, with geometry for GeoServer (WMS/WFS)
CREATE OR REPLACE VIEW health.v_zero_dose_warning AS
SELECT d.district_code, d.district, d.region, z.period, z.penta1_cov_3m, z.zero_dose_12m,
       CASE WHEN z.penta1_cov_3m < 0.70 THEN 'ALERT'
            WHEN z.penta1_cov_3m < 0.80 THEN 'WARNING'
            WHEN z.penta1_cov_3m < 0.90 THEN 'WATCH'
            ELSE 'NORMAL' END AS level,
       d.geom
FROM health.v_zero_dose z
JOIN admin.districts d USING (district_code)
WHERE z.period = (SELECT MAX(period) FROM health.immunisation_monthly);

-- Example spatial query: districts at WARNING+ that border an ALERT district (spillover risk)
-- SELECT DISTINCT a.district FROM health.v_zero_dose_warning a
-- JOIN health.v_zero_dose_warning b ON ST_Touches(a.geom, b.geom)
-- WHERE a.level IN ('WARNING','ALERT') AND b.level = 'ALERT' AND a.district_code <> b.district_code;
