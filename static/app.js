"use strict";

const slots = document.querySelector("#slots");
const bookings = document.querySelector("#bookings");
const notice = document.querySelector("#notice");
const availability = document.querySelector("#availability-title");
const bookingsTitle = document.querySelector("#bookings-title");
let moving = null;
let busy = false;
const busyUi = (value) => {
  busy = value;
  slots.setAttribute("aria-busy", String(value));
  bookings.setAttribute("aria-busy", String(value));
};
const speak = (message, isError = false) => {
  notice.className = isError ? "notice error" : "notice";
  notice.textContent = message;
};
const element = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
function dayLabel(iso) {
  return new Intl.DateTimeFormat("en-US", {weekday: "long", month: "short", day: "numeric", timeZone: "UTC"})
    .format(new Date(iso + "T12:00:00Z"));
}
function button(text, label, click, cls) {
  const node = element("button", text, cls);
  node.type = "button";
  node.setAttribute("aria-label", label);
  node.addEventListener("click", click);
  return node;
}
async function request(path, method = "GET", data) {
  const res = await fetch(path, {
    method,
    ...(data ? {headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)} : {}),
  });
  const payload = await res.json();
  if (!res.ok) throw new Error(payload.error || "The request could not be completed.");
  return payload;
}
async function change(path, method, data, success) {
  if (busy) return;
  busyUi(true);
  try {
    await request(path, method, data);
    moving = null;
    try {
      await refresh();
      speak(success);
      bookingsTitle.focus();
    } catch {
      speak(success + " Reload the page to refresh the schedule.");
    }
  } catch (error) {
    speak(error.message, true);
    try { await refresh(); availability.focus(); } catch { /* Original error is already visible. */ }
  } finally {
    busyUi(false);
  }
}
function render(state) {
  slots.replaceChildren();
  bookings.replaceChildren();
  if (moving && !state.bookings.some((item) => item.id === moving)) moving = null;
  if (moving) {
    const instructions = element("div", undefined, "reschedule");
    instructions.append(element("p", "Choose a new time. Your original booking stays in place until the change succeeds."));
    instructions.append(button("Keep existing time", "Cancel rescheduling and keep the existing time", () => {
      if (busy) return;
      moving = null;
      render(state);
      speak("Your booking was not changed.");
      bookingsTitle.focus();
    }, "secondary"));
    slots.append(instructions);
  }
  const byDay = new Map();
  for (const slot of state.slots) {
    if (!byDay.has(slot.date)) byDay.set(slot.date, []);
    byDay.get(slot.date).push(slot);
  }
  for (const [date, items] of byDay) {
    const day = element("section", undefined, "day");
    day.append(element("h3", dayLabel(date)));
    for (const slot of items) {
      const row = element("div", undefined, "slot");
      const label = element("div", undefined, "slot-meta");
      label.append(element("strong", slot.time), element("span", slot.provider + " · " + slot.service));
      row.append(label);
      if (slot.available) {
        const action = moving ? "Move here" : "Book";
        row.append(button(action, action + ": " + dayLabel(date) + ", " + slot.time + ", " + slot.provider, () => {
          const id = moving;
          void change(id ? "/api/bookings/" + id : "/api/bookings",
                      id ? "PATCH" : "POST", {slotId: slot.id},
                      (id ? "Booking moved to " : "Booked ") + dayLabel(date) + " at " + slot.time + ".");
        }));
      } else {
        row.append(element("span", "Booked", "taken"));
      }
      day.append(row);
    }
    slots.append(day);
  }
  if (!state.bookings.length) bookings.append(element("p", "No times booked yet. Choose an available time to get started.", "muted"));
  for (const item of state.bookings) {
    const card = element("article", undefined, "booking-card");
    const when = dayLabel(item.slot.date) + " at " + item.slot.time;
    card.append(element("h3", when), element("p", item.slot.provider + " · " + item.slot.service, "muted"));
    const actions = element("div", undefined, "actions");
    actions.append(button("Reschedule", "Reschedule " + when, () => {
      if (busy) return;
      moving = item.id;
      render(state);
      speak("Rescheduling: choose an available time.");
      availability.focus();
    }, "secondary"));
    actions.append(button("Cancel", "Cancel " + when, () => {
      if (busy || !window.confirm("Cancel the demo booking for " + when + "?")) return;
      void change("/api/bookings/" + item.id, "DELETE", undefined, "Booking cancelled. That time is available again.");
    }, "secondary danger"));
    card.append(actions);
    bookings.append(card);
  }
}
async function refresh() {
  render(await request("/api/schedule"));
}
void refresh().catch(() => {
  slots.replaceChildren(button("Retry", "Reload the fictional schedule", () => {
    void refresh().then(() => speak("Schedule loaded.")).catch(() => speak("Could not load the demo schedule.", true));
  }));
  speak("Could not load the demo schedule.", true);
});
