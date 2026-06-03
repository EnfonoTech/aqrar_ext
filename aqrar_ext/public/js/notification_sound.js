frappe.realtime.on("notification", function () {
	frappe.db.get_value("User", frappe.session.user, "custom_enable_sound_alerts", function (r) {
		if (r && r.custom_enable_sound_alerts) {
			var audio = new Audio("/assets/frappe/sounds/alert.mp3");
			audio.play().catch(function () { /* browser may block autoplay */ });
		}
	});
});
