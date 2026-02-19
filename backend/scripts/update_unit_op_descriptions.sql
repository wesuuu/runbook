-- Update existing unit op definitions with template descriptions.
-- Run from psql:  \i scripts/update_unit_op_descriptions.sql

BEGIN;

UPDATE unit_op_definitions SET description = 'Prepare {{volume_L}}L of {{buffer_name}} by dissolving {{components}} in {{solvent}}. Adjust to pH {{pH_target}} (+/- {{pH_tolerance}}) using {{pH_agent}}. Store at {{storage_temp_c}}°C.'
WHERE name = 'Buffer Preparation';

UPDATE unit_op_definitions SET description = 'Reconstitute {{volume_L}}L of {{media_name}} using {{basal_medium}}. Add {{supplements}}, adjust to pH {{pH_target}}, verify osmolality at {{osmolality_mOsm}} mOsm/kg. Sterile filter: {{filter_after}}. Store at {{storage_temp_c}}°C.'
WHERE name = 'Media Preparation';

UPDATE unit_op_definitions SET description = 'Seed cells at {{cell_density}} cells/mL into {{vessel_type}} with {{volume_mL}}mL working volume.'
WHERE name = 'Seeding';

UPDATE unit_op_definitions SET description = 'Incubate at {{temperature_C}}°C with {{CO2_percent}}% CO2 at {{rpm}} RPM for {{duration_hours}} hours.'
WHERE name = 'Incubation';

UPDATE unit_op_definitions SET description = 'Count cells using {{method}} method with {{dilution_factor}}x dilution factor.'
WHERE name = 'Cell Counting';

UPDATE unit_op_definitions SET description = 'Transfect cells using {{reagent}} with {{dna_amount_ug}}ug DNA via {{method}} method.'
WHERE name = 'Transfection';

UPDATE unit_op_definitions SET description = 'Harvest cells using {{method}} method, centrifuge at {{centrifuge_rcf}}xg.'
WHERE name = 'Harvest';

UPDATE unit_op_definitions SET description = 'Centrifuge at {{rcf_g}}xg for {{duration_min}} minutes at {{temperature_C}}°C.'
WHERE name = 'Centrifugation';

UPDATE unit_op_definitions SET description = 'Filter {{volume_L}}L through {{filter_type}} membrane ({{filter_size_um}}um pore size).'
WHERE name = 'Filtration';

UPDATE unit_op_definitions SET description = 'Purify using {{column_type}} column with {{resin}} resin at {{flow_rate_mL_min}} mL/min flow rate.'
WHERE name = 'Chromatography';

UPDATE unit_op_definitions SET description = 'Adjust solution to pH {{target_pH}} using {{acid_or_base}}.'
WHERE name = 'pH Adjustment';

UPDATE unit_op_definitions SET description = 'Mix at {{speed_rpm}} RPM for {{duration_min}} minutes at {{temperature_C}}°C.'
WHERE name = 'Mixing';

UPDATE unit_op_definitions SET description = 'Collect {{volume_mL}}mL sample into {{container_type}}, store at {{storage_temp_C}}°C.'
WHERE name = 'Sample Collection';

UPDATE unit_op_definitions SET description = 'Run {{assay_type}} assay using {{method}} method.'
WHERE name = 'Assay';

UPDATE unit_op_definitions SET description = 'Fill {{fill_volume_mL}}mL into {{container_type}} at {{fill_speed}} speed.'
WHERE name = 'Fill';

UPDATE unit_op_definitions SET description = 'Lyophilize at {{shelf_temp_C}}°C shelf temperature, {{chamber_pressure_mTorr}} mTorr chamber pressure for {{duration_hours}} hours.'
WHERE name = 'Lyophilization';

UPDATE unit_op_definitions SET description = 'Perform {{inspection_type}} visual inspection. Acceptance criteria: {{acceptance_criteria}}.'
WHERE name = 'Visual Inspection';

COMMIT;
