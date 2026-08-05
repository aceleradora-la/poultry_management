/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onMounted, onPatched, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class PoultryStandardTrackingReport extends Component {
    static template = "poultry_management.PoultryStandardTrackingReport";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.rootRef = useRef("root");
        // El encabezado sticky de dos filas necesita saber la altura REAL de la
        // primera fila (los nombres de indicadores se parten en varias líneas)
        // para posicionar la segunda; se mide tras cada render.
        onMounted(() => this._updateStickyOffsets());
        onPatched(() => this._updateStickyOffsets());
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
            // Despliegue por día: llaves "semana:lote" abiertas (modo comparación,
            // segundo nivel) y caché del detalle diario por semana (carga perezosa).
            expandedBatchDays: {},
            dailyCache: {},
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

    _updateStickyOffsets() {
        const root = this.rootRef.el;
        if (!root) {
            return;
        }
        for (const table of root.querySelectorAll("table")) {
            const firstRow = table.querySelector("thead tr:first-child");
            if (firstRow) {
                table.style.setProperty(
                    "--poultry-thead-row1-h",
                    `${firstRow.getBoundingClientRect().height}px`
                );
            }
        }
    }

    get title() {
        const base = this.isCalendarAxis ? "Estándares Semana" : "Estándares Semana Vida";
        if (this.fixedPeriod === "crianza") {
            return `${base} - Crianza`;
        }
        if (this.fixedPeriod === "produccion") {
            return `${base} - Producción`;
        }
        return base;
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

    async onRowClick(week) {
        // Un lote: despliega los días de la semana. Comparación: despliega el
        // detalle por lote (los días de cada lote se abren en el segundo nivel).
        const willExpand = !this.state.expandedWeeks[week];
        this.state.expandedWeeks[week] = willExpand;
        if (willExpand && !this.isComparison) {
            await this._loadWeekDaily(week);
        }
    }

    async onBatchDayToggle(week, batchId) {
        const key = `${week}:${batchId}`;
        const willExpand = !this.state.expandedBatchDays[key];
        this.state.expandedBatchDays[key] = willExpand;
        if (willExpand) {
            await this._loadWeekDaily(week);
        }
    }

    async _loadWeekDaily(week) {
        if (this.state.dailyCache[week]) {
            return;
        }
        try {
            this.state.dailyCache[week] = await this.orm.call(
                "poultry.standard.tracking.report.wizard",
                "get_week_daily_data",
                [this.wizardId, week]
            );
        } catch (error) {
            this.state.error = (error && error.data && error.data.message) || String(error);
        }
    }

    getWeekDays(week, batchId) {
        // null = todavía cargando; el server devuelve las llaves como string.
        const weekData = this.state.dailyCache[week];
        return weekData ? weekData[String(batchId)] || { batch_name: "", has_daily: false, days: [] } : null;
    }

    getRowBatches(row) {
        // El detalle por lote lo precalcula el servidor (row.batch_rows), para que
        // la pantalla, el PDF y el Excel muestren exactamente lo mismo.
        return row.batch_rows || [];
    }

    get isCalendarAxis() {
        // Del header, no de los params de la acción: así sobrevive a los refrescos
        // (cambiar de lote o de versión rearma los datos con su propio header).
        return !!(this.header && this.header.axis === "calendar_week");
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
        // El detalle diario depende de los lotes seleccionados: se invalida al
        // cambiar la selección o la versión (recargarlo cuesta una llamada).
        this.state.dailyCache = {};
        this.state.expandedBatchDays = {};
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
