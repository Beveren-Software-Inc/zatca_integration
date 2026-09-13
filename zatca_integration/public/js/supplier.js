frappe.ui.form.on("Supplier", {
	tax_category(frm) {
		if (frm.doc.__islocal) {
			return;
		}
		frappe.show_alert({
			message: __("Linked addresses will update VAT Category on save."),
			indicator: "blue",
		});
	},
});
