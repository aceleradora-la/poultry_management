/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class PoultryStandardTrackingReport extends Component {
    static template = "poultry_management.PoultryStandardTrackingReport";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.wizardId = this.props.action.params.wizard_id;
        // Período fijo (menús "Seguimiento Estándares - Crianza/Producción"): el
        // reporte muestra solo ese período y oculta las pestañas. Sin valor, se
        // mantienen las pestañas Crianza/Producción (comportamiento anterior).
        this.fixedPeriod = this.props.action.params.period || null;
        this.state = useState({
            period: this.fixedPeriod || "crianza",
            data: null,
            batches: [],
            loading: true,
            error: null,
            hiddenIndicatorIds: {},
            expandedWeeks: {},
        });
        onWillStart(async () => {
            try {
                const [data, batches] = await Promise.all([
                    this.orm.call(
                        "poultry.standard.tracking.report.wizard",
                        "get_report_data",
                        [this.wizardId]
                    ),
                    this.orm.searchRead(
                        "poultry.batch", [], ["id", "name", "genetics_id"], { order: "birth_date desc" }
                    ),
                ]);
                this.state.data = data;
                this.state.batches = batches;
            } catch (error) {
                this.state.error = (error && error.data && error.data.message) || String(error);
            } finally {
                this.state.loading = false;
            }
        });
    }

    setPeriod(period) {
        this.state.period = period;
    }

    get title() {
        if (this.fixedPeriod === "crianza") {
            return "Seguimiento Estándares - Crianza";
        }
        if (this.fixedPeriod === "produccion") {
            return "Seguimiento Estándares - Producción";
        }
        return "Seguimiento de Estándares";
    }

    get currentData() {
        return this.state.data ? this.state.data[this.state.period] : null;
    }

    get header() {
        return this.state.data ? this.state.data.header : null;
    }

    get visibleIndicators() {
        if (!this.currentData) {
            return [];
        }
        return this.currentData.indicators.filter(
            (indicator) => !this.state.hiddenIndicatorIds[indicator.id]
        );
    }

    toggleIndicatorVisibility(indicatorId) {
        this.state.hiddenIndicatorIds[indicatorId] = !this.state.hiddenIndicatorIds[indicatorId];
    }

    showAllIndicators() {
        this.state.hiddenIndicatorIds = {};
    }

    hideAllIndicators() {
        const hidden = {};
        (this.currentData ? this.currentData.indicators : []).forEach((indicator) => {
            hidden[indicator.id] = true;
        });
        this.state.hiddenIndicatorIds = hidden;
    }

    get isComparison() {
        return !!(this.header && this.header.is_comparison);
    }

    get selectedBatches() {
        if (!this.header) {
            return [];
        }
        const byId = Object.fromEntries(this.state.batches.map((b) => [b.id, b]));
        return (this.header.batch_ids || [this.header.batch_id])
            .map((id) => byId[id])
            .filter(Boolean);
    }

    get addableBatches() {
        if (!this.header) {
            return [];
        }
        const selectedIds = this.header.batch_ids || [this.header.batch_id];
        const primary = this.state.batches.find((b) => b.id === this.header.batch_id);
        const primaryGenetics = primary && primary.genetics_id ? primary.genetics_id[0] : null;
        return this.state.batches.filter(
            (b) =>
                !selectedIds.includes(b.id) &&
                (!primaryGenetics || (b.genetics_id && b.genetics_id[0] === primaryGenetics))
        );
    }

    onRowClick(week) {
        if (!this.isComparison) {
            return;
        }
        this.state.expandedWeeks[week] = !this.state.expandedWeeks[week];
    }

    getRowBatches(row) {
        const map = {};
        for (const indicator of this.visibleIndicators) {
            const cell = row.cells[indicator.id];
            for (const bv of (cell && cell.batch_values) || []) {
                if (!map[bv.batch_id]) {
                    map[bv.batch_id] = {
                        batch_id: bv.batch_id,
                        name: bv.batch_name,
                        bird_count: bv.bird_count,
                        date: bv.date,
                        live_birds: (row.live_birds_by_batch || {})[bv.batch_id],
                        values: {},
                    };
                }
                map[bv.batch_id].values[indicator.id] = bv;
            }
        }
        return Object.values(map);
    }

    async onAddBatch(ev) {
        const batchId = parseInt(ev.target.value, 10);
        ev.target.value = "";
        if (!batchId || !this.header) {
            return;
        }
        const ids = (this.header.batch_ids || [this.header.batch_id]).concat([batchId]);
        this.state.expandedWeeks = {};
        await this._reload("update_batches", ids);
    }

    async onRemoveBatch(batchId) {
        if (!this.header) {
            return;
        }
        const ids = (this.header.batch_ids || [this.header.batch_id]).filter(
            (id) => id !== batchId
        );
        if (!ids.length) {
            return;
        }
        this.state.expandedWeeks = {};
        await this._reload("update_batches", ids);
    }

    async onVersionChange(ev) {
        const versionId = parseInt(ev.target.value, 10);
        await this._reload("update_version", versionId);
    }

    async _reload(method, arg) {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call(
                "poultry.standard.tracking.report.wizard",
                method,
                [this.wizardId, arg]
            );
        } catch (error) {
            this.state.error = (error && error.data && error.data.message) || String(error);
        } finally {
            this.state.loading = false;
        }
    }

    async exportPdf() {
        await this.action.doAction({
            type: "ir.actions.report",
            report_name: "poultry_management.report_poultry_standard_tracking",
            report_type: "qweb-pdf",
            context: { active_ids: [this.wizardId] },
        });
    }

    exportXlsx() {
        window.location = `/poultry/standard_tracking/xlsx/${this.wizardId}`;
    }
}

registry.category("actions").add("poultry_standard_tracking_report", PoultryStandardTrackingReport);
