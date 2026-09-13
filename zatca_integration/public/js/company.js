frappe.ui.form.on("Company", {
	custom_zatca_setup(frm) {
		run_zatca_vat_setup(frm);
	},
});

async function run_zatca_vat_setup(frm) {
	if (frm.is_new()) {
		frappe.msgprint({
			title: __("Save Required"),
			message: __("Please save the company before running ZATCA setup."),
			indicator: "orange",
		});
		return;
	}

	if (frm.doc.country !== "Saudi Arabia") {
		frappe.msgprint({
			title: __("Not Applicable"),
			message: __("ZATCA VAT setup is only available for companies in Saudi Arabia."),
			indicator: "orange",
		});
		return;
	}

	const already_done = cint(frm.doc.custom_zatca_vat_setup_done);
	if (already_done) {
		frappe.confirm(
			__(
				"ZATCA VAT setup was already completed for this company. Run again to create any missing items?"
			),
			() => start_zatca_vat_setup(frm, 1),
			() => {}
		);
		return;
	}

	start_zatca_vat_setup(frm, 0);
}

async function start_zatca_vat_setup(frm, force) {
	let steps;
	try {
		steps = await frappe.xcall(
			"zatca_integration.saudi_arabia_electronic_invoicing.vat_setup.get_ksa_vat_setup_steps"
		);
	} catch (e) {
		return;
	}

	const dialog = build_progress_dialog(steps);
	dialog.show();

	frm.dashboard.set_headline_alert(
		`<div class="form-message blue"><strong>${__("ZATCA Setup")}</strong>: ${__(
			"Running…"
		)}</div>`
	);

	for (let i = 0; i < steps.length; i++) {
		const step = steps[i];
		set_step_state(dialog, step.name, "running");
		frappe.show_progress(__("ZATCA Setup"), i + 1, steps.length, __(step.label));

		try {
			const result = await frappe.xcall(
				"zatca_integration.saudi_arabia_electronic_invoicing.vat_setup.run_ksa_vat_setup_step",
				{
					company: frm.doc.name,
					step: step.name,
					force: force,
				}
			);

			if (result && result.skipped && result.reason === "already_done") {
				set_step_state(dialog, step.name, "skipped", result.message);
				finish_setup_dialog(dialog, frm, "blue", result.message || __("Setup already completed."));
				return;
			}

			set_step_state(dialog, step.name, "done", result && result.message);
		} catch (e) {
			set_step_state(dialog, step.name, "failed", e.message || __("Failed"));
			finish_setup_dialog(dialog, frm, "red", __("ZATCA setup failed. Check the Error Log."));
			return;
		}
	}

	finish_setup_dialog(
		dialog,
		frm,
		"green",
		__("KSA VAT accounts, tax templates, categories, and tax rules are configured.")
	);
	frm.reload_doc();
}

function finish_setup_dialog(dialog, frm, indicator, message) {
	frappe.hide_progress();
	dialog._can_close = true;
	dialog.set_secondary_action_label(__("Close"));
	dialog.$wrapper.find(".modal-header .btn-modal-close").show();

	const headline_color = indicator === "green" ? "green" : indicator === "red" ? "red" : "blue";
	const headline_label =
		indicator === "green" ? __("Completed") : indicator === "red" ? __("Failed") : __("Skipped");
	frm.dashboard.set_headline_alert(
		`<div class="form-message ${headline_color}"><strong>${__("ZATCA Setup")}</strong>: ${headline_label}</div>`
	);
	frappe.show_alert({ message: message, indicator: indicator });
}

function build_progress_dialog(steps) {
	const rows = steps
		.map(
			(step) => `
			<div class="zatca-setup-step" data-step="${frappe.utils.escape_html(step.name)}"
				style="display:flex;align-items:flex-start;gap:10px;padding:8px 0;border-bottom:1px solid var(--border-color);">
				<span class="zatca-setup-indicator" style="min-width:18px;margin-top:2px;font-weight:600;">○</span>
				<div style="flex:1;">
					<div class="zatca-setup-label" style="font-weight:500;">${frappe.utils.escape_html(__(step.label))}</div>
					<div class="zatca-setup-detail text-muted small" style="margin-top:2px;"></div>
				</div>
			</div>`
		)
		.join("");

	const dialog = new frappe.ui.Dialog({
		title: __("ZATCA VAT Setup"),
		size: "large",
		static: true,
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "progress",
				options: `<div class="zatca-setup-progress">${rows}</div>`,
			},
		],
		secondary_action_label: __("Please wait…"),
		secondary_action() {
			if (dialog._can_close) {
				dialog.hide();
			}
		},
	});

	dialog._can_close = false;
	dialog.$wrapper.find(".modal-header .btn-modal-close").hide();
	return dialog;
}

function set_step_state(dialog, step_name, state, detail) {
	const $row = dialog.$wrapper.find(`.zatca-setup-step[data-step="${step_name}"]`);
	if (!$row.length) {
		return;
	}

	const $indicator = $row.find(".zatca-setup-indicator");
	const $detail = $row.find(".zatca-setup-detail");

	const styles = {
		pending: { text: "○", color: "var(--text-muted)" },
		running: { text: "●", color: "var(--blue-500)" },
		done: { text: "✓", color: "var(--green-500)" },
		skipped: { text: "–", color: "var(--text-muted)" },
		failed: { text: "✕", color: "var(--red-500)" },
	};
	const style = styles[state] || styles.pending;

	$indicator.text(style.text).css("color", style.color);
	if (detail) {
		$detail.text(detail);
	} else if (state === "running") {
		$detail.text(__("Creating…"));
	} else if (state === "done") {
		$detail.text(__("Done"));
	}
}
