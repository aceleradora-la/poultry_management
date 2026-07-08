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
        this.state = useState({
            period: "crianza",
            data: null,
            loading: true,
            error: null,
        });
        onWillStart(async () => {
            try {
                this.state.data = await this.orm.call(
                    "poultry.standard.tracking.report.wizard",
                    "get_report_data",
                    [this.wizardId]
                );
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

    get currentData() {
        return this.state.data ? this.state.data[this.state.period] : null;
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
