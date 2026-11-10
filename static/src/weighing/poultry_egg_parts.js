import { Component, useState, onWillStart, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { formatNum, normalizeNum, parseNum, selectOnFocus } from "./poultry_number_input";

const MODEL = "poultry.egg.collection";

/**
 * Partes de producción de huevos desde el celular: galpones de hoy → Inicial por calibre
 * (paso 1) → Bruto y peso medio (paso 2) → resumen y completar. Cada celda se guarda al
 * salir de ella; Siguiente/Enter recorre las celdas hacia la derecha y baja de calibre.
 * Las aves muertas y los consumos no van en el parte: se cargan en la OF de Huevo sin
 * Clasificar (PoultryFarmData) cuando la oficina confirma el Cierre de Galpón.
 */
export class PoultryEggParts extends Component {
    static template = "poultry_management.PoultryEggParts";
    static props = { onHome: Function };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            screen: "coops", // coops | initial | gross | summary
            date: "",
            coops: [],
            late: [],
            record: null,
            form: [], // [{ id, calibre, qty: ["", "", ""], pm: "" }] en el mismo orden que record.lines
            busy: false,
        });
        this.focusPending = false;
        // Los guardados de celdas van en fila: una red lenta no puede hacer que una celda
        // vieja pise a la siguiente, y Guardar/Revisar esperan a que termine la fila.
        this.saveQueue = Promise.resolve();
        // Lo último tipeado en cada celda ("línea:columna"), tecla por tecla y sin redibujar.
        // Es la red de seguridad si el evento de cambio de una celda no llega (visto en
        // pre-prod: se perdieron valores sueltos al tipear rápido).
        this.drafts = new Map();
        this.selectOnFocus = selectOnFocus;
        onWillStart(() => this.loadCoops());
        onPatched(() => this.focusFirst());
    }

    enqueue(job) {
        const run = this.saveQueue.then(job, job);
        this.saveQueue = run.catch(() => {});
        return run;
    }

    notifyError(error) {
        const message = (error.data && error.data.message) || error.message || String(error);
        this.notification.add(message, { type: "danger" });
    }

    // ------------------------------------------------------------------
    // Formato y unidades
    // ------------------------------------------------------------------
    fmt(value) {
        return Math.round(value || 0).toLocaleString("es-AR");
    }

    d1(value) {
        return (value || 0).toLocaleString("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    }

    /** Valor para una celda: sin ceros, coma decimal y sin separador de miles. */
    qtyText(value) {
        return formatNum(value);
    }

    get dateLabel() {
        const date = this.state.date ? new Date(this.state.date + "T12:00:00") : new Date();
        const label = date.toLocaleDateString("es-AR", { weekday: "long", day: "numeric", month: "long" });
        return label.charAt(0).toUpperCase() + label.slice(1);
    }

    get factors() {
        return this.state.record.uoms.map((uom) => uom.factor);
    }

    get unitNames() {
        return this.state.record.uoms.map((uom) => uom.name);
    }

    eggsOf(values) {
        return values.reduce((sum, value, index) => sum + parseNum(value) * (this.factors[index] || 0), 0);
    }

    /** Reparte huevos en las unidades del parte, de la mayor a la menor (17 cajón · 8 maple · 25 huevo). */
    splitLabel(eggs) {
        let rest = Math.max(Math.round(eggs || 0), 0);
        const parts = this.factors.map((factor, index) => {
            if (!factor) {
                return 0;
            }
            if (index === this.factors.length - 1) {
                return rest;
            }
            const count = Math.floor(rest / factor);
            rest -= count * factor;
            return count;
        });
        return parts
            .map((count, index) => `${count} ${(this.unitNames[index] || "").toLowerCase()}`)
            .filter((text) => !text.endsWith(" "))
            .join(" · ");
    }

    async call(method, args = [], kwargs = {}) {
        this.state.busy = true;
        try {
            await this.saveQueue;
            return await this.orm.call(MODEL, method, args, kwargs);
        } catch (error) {
            this.notifyError(error);
            throw error;
        } finally {
            this.state.busy = false;
        }
    }

    // ------------------------------------------------------------------
    // Galpones de hoy
    // ------------------------------------------------------------------
    async loadCoops() {
        const data = await this.call("poultry_mobile_coops");
        this.state.date = data.date;
        this.state.coops = data.coops;
        this.state.late = data.late;
        this.state.screen = "coops";
        this.state.record = null;
    }

    /** nobirds | none (sin inicial) | counted | completed | done */
    status(item) {
        const rec = item.record;
        if (!rec) {
            return item.live_bird_count ? "none" : "nobirds";
        }
        return rec.state === "draft" ? "none" : rec.state;
    }

    get chips() {
        const counts = { completed: 0, counted: 0, none: 0 };
        for (const item of this.state.coops) {
            const status = this.status(item);
            if (status === "completed" || status === "done") {
                counts.completed += 1;
            } else if (status === "counted") {
                counts.counted += 1;
            } else if (status === "none") {
                counts.none += 1;
            }
        }
        const chips = [];
        if (counts.completed) {
            chips.push({ cls: "o_pw_chip_ok", text: `${counts.completed} ${counts.completed === 1 ? "completo" : "completos"}` });
        }
        if (counts.counted) {
            chips.push({ cls: "o_pw_chip_primary", text: `${counts.counted} falta el bruto` });
        }
        if (counts.none) {
            chips.push({ cls: "", text: `${counts.none} sin inicial` });
        }
        if (this.state.late.length) {
            chips.push({ cls: "o_pw_chip_warn", text: `${this.state.late.length} ${this.state.late.length === 1 ? "atrasado" : "atrasados"}` });
        }
        return chips;
    }

    async openCoop(item) {
        this.state.record = await this.call("poultry_mobile_open_coop", [item.coop_id]);
        this.route();
    }

    async openRecord(recordId) {
        this.state.record = await this.call("poultry_mobile_data", [[recordId]]);
        this.route();
    }

    /** La pantalla que corresponde al estado del parte. */
    route() {
        const state = this.state.record.state;
        if (state === "draft") {
            this.showInitial();
        } else if (state === "counted") {
            this.showGross();
        } else {
            this.state.screen = "summary";
        }
    }

    fillForm(kind) {
        this.drafts = new Map();
        this.state.form = this.state.record.lines.map((line) => ({
            id: line.id,
            calibre: line.calibre,
            qty: line[kind].map((value) => this.qtyText(value)),
            pm: kind === "final" ? this.qtyText(line.average_weight) : "",
        }));
    }

    showInitial() {
        this.fillForm("initial");
        this.state.screen = "initial";
        this.focusPending = true;
    }

    showGross() {
        this.fillForm("final");
        this.state.screen = "gross";
        this.focusPending = true;
    }

    focusFirst() {
        if (!this.focusPending) {
            return;
        }
        this.focusPending = false;
        const inputs = [...document.querySelectorAll(".o_pw_eggs_grid input")];
        const target = inputs.find((input) => !input.value) || inputs[0];
        if (target) {
            target.focus();
            target.select();
        }
    }

    // ------------------------------------------------------------------
    // Carga por calibre (inicial y bruto)
    // ------------------------------------------------------------------
    get kind() {
        return this.state.screen === "gross" ? "final" : "initial";
    }

    payload() {
        return this.state.form.map((line) => {
            const item = { line_id: line.id, qty: line.qty.map((value) => parseNum(value)) };
            if (this.kind === "final") {
                item.average_weight = parseNum(line.pm);
            }
            return item;
        });
    }

    cellValue(line, col) {
        return col === "pm" ? line.pm : line.qty[col];
    }

    /** La línea y la columna de una celda, leídas de sus atributos data-line / data-col. */
    cellOf(input) {
        const line = this.state.form.find((l) => String(l.id) === input.dataset.line);
        const col = input.dataset.col === "pm" ? "pm" : parseInt(input.dataset.col);
        return { line, col };
    }

    /** Cada tecla queda en el borrador de la celda; no toca el estado (no redibuja). */
    onCellInput(ev) {
        this.drafts.set(`${ev.target.dataset.line}:${ev.target.dataset.col}`, ev.target.value);
    }

    /**
     * Pasa una celda al estado y la guarda (si cambió). Cada celda se guarda al salir de ella:
     * si el celular se apaga, no se pierde nada. El guardado NO toca el estado al volver: el
     * operador ya está escribiendo la celda siguiente y un redibujo le borraría lo tipeado.
     */
    commitCell(input) {
        const { line, col } = this.cellOf(input);
        if (!line) {
            return;
        }
        const value = normalizeNum(input.value);
        this.drafts.set(`${input.dataset.line}:${input.dataset.col}`, value);
        if (input.value !== value) {
            input.value = value;
        }
        if (value === this.cellValue(line, col)) {
            return;
        }
        if (col === "pm") {
            line.pm = value;
        } else {
            line.qty[col] = value;
        }
        const args = [[this.state.record.id], this.kind, this.payload()];
        return this.enqueue(() =>
            this.orm.call(MODEL, "poultry_mobile_write_values", args).catch((error) => this.notifyError(error))
        );
    }

    onCellChange(ev) {
        return this.commitCell(ev.target);
    }

    /** Siguiente/Enter: guarda la celda (sin esperar al evento de cambio) y pasa a la próxima. */
    onKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        this.commitCell(ev.target);
        const inputs = [...ev.target.closest(".o_pw_eggs_grid").querySelectorAll("input")];
        const next = inputs[inputs.indexOf(ev.target) + 1];
        if (next) {
            next.focus();
            next.select();
        } else {
            ev.target.blur();
        }
    }

    /**
     * Antes de Guardar inicial / Revisar se vuelve a leer cada celda: lo que se guarda es lo
     * que el operador tipeó, aunque el evento de cambio de alguna celda no haya llegado. Si la
     * pantalla quedó vacía pero la celda tiene borrador, gana el borrador.
     */
    syncFromCells() {
        for (const input of document.querySelectorAll(".o_pw_eggs_grid input[data-line]")) {
            const { line, col } = this.cellOf(input);
            if (!line) {
                continue;
            }
            const draft = this.drafts.get(`${input.dataset.line}:${input.dataset.col}`);
            const typed = input.value !== "" ? input.value : draft || "";
            const value = normalizeNum(typed);
            if (value !== this.cellValue(line, col)) {
                if (col === "pm") {
                    line.pm = value;
                } else {
                    line.qty[col] = value;
                }
            }
        }
    }

    rowInfo(line, index) {
        const source = this.state.record.lines[index];
        const initialEggs = source ? source.initial_eggs : 0;
        const typed = line.qty.some((value) => value !== "");
        if (!typed) {
            return { typed: false, error: false, text: `Inicial ${this.fmt(initialEggs)} huevos` };
        }
        const finalEggs = this.eggsOf(line.qty);
        if (finalEggs < initialEggs) {
            return {
                typed: true,
                error: true,
                text: `Menor que el inicial (${this.fmt(initialEggs)} huevos): revisá la cuenta`,
            };
        }
        const produced = finalEggs - initialEggs;
        return { typed: true, error: false, text: `Produce ${this.splitLabel(produced)} = ${this.fmt(produced)}` };
    }

    get grossRows() {
        return this.state.form.map((line, index) => ({ line, info: this.rowInfo(line, index) }));
    }

    get canReview() {
        const rows = this.grossRows;
        return rows.some((row) => row.info.typed) && !rows.some((row) => row.info.error);
    }

    async saveInitial() {
        const { id, coop } = this.state.record;
        this.syncFromCells();
        this.state.record = await this.call("poultry_mobile_save_initial", [[id], this.payload()]);
        this.notification.add(`Inicial de ${coop} guardado. A la tarde falta el bruto.`, { type: "success" });
        await this.loadCoops();
    }

    async copyPrevious() {
        this.state.record = await this.call("poultry_mobile_copy_previous_gross", [[this.state.record.id]]);
        this.showInitial();
    }

    async review() {
        this.syncFromCells();
        if (!this.canReview) {
            this.notification.add("Revisá las filas en rojo: hay un bruto por debajo del inicial.", { type: "warning" });
            return;
        }
        this.state.record = await this.call("poultry_mobile_save_gross", [[this.state.record.id], this.payload()]);
        this.state.screen = "summary";
    }

    async complete() {
        const { id, coop } = this.state.record;
        this.state.record = await this.call("poultry_mobile_complete", [[id]]);
        this.notification.add(`Parte de ${coop} completado. La oficina lo procesa.`, { type: "success" });
        await this.loadCoops();
    }

    async reopen() {
        this.state.record = await this.call("poultry_mobile_reopen", [[this.state.record.id]]);
    }

    /** Corregir el bruto: si el parte ya estaba completado, primero se reabre. */
    correctGross() {
        if (this.state.record.state !== "completed") {
            this.showGross();
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: "Corregir el bruto",
            body: "El parte vuelve a Bruto para corregirlo. Después hay que completarlo de nuevo.",
            confirmLabel: "Corregir",
            cancelLabel: "Cancelar",
            confirm: async () => {
                await this.reopen();
                this.showGross();
            },
            cancel: () => {},
        });
    }

    correctInitial() {
        this.dialog.add(ConfirmationDialog, {
            title: "Corregir el inicial",
            body: "El parte vuelve a Inicio: el bruto cargado se conserva, pero hay que guardar el inicial de nuevo.",
            confirmLabel: "Corregir",
            cancelLabel: "Cancelar",
            confirm: async () => {
                await this.reopen();
                this.showInitial();
            },
            cancel: () => {},
        });
    }

    // ------------------------------------------------------------------
    // Resumen
    // ------------------------------------------------------------------
    get summaryRows() {
        const total = this.state.record.total_eggs || 0;
        return this.state.record.lines.map((line) => ({
            id: line.id,
            calibre: line.calibre,
            split: this.splitLabel(line.produced_eggs),
            eggs: this.fmt(line.produced_eggs),
            pct: total ? this.d1((line.produced_eggs / total) * 100) + " %" : "—",
            pm: line.average_weight ? `peso medio ${this.d1(line.average_weight)} g` : "sin peso medio",
            noPm: !line.average_weight && line.produced_eggs > 0,
        }));
    }

    get noPmCalibres() {
        return this.summaryRows.filter((row) => row.noPm).map((row) => row.calibre);
    }

    get vsPrevious() {
        const rec = this.state.record;
        if (!rec.previous_total_eggs) {
            return "";
        }
        const pct = (rec.total_eggs / rec.previous_total_eggs - 1) * 100;
        return (pct >= 0 ? "+" : "−") + this.d1(Math.abs(pct)) + " %";
    }
}
