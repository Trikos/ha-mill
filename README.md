# Mill for Home Assistant — power limit fix

A drop-in replacement for Home Assistant's built-in [Mill](https://www.home-assistant.io/integrations/mill)
integration that adds a working **power limit** for Mill heaters on the cloud connection.

## The problem

The built-in integration exposes a `number` entity (e.g. `number.<heater>_power`) that looks like a power
limit. It writes `max_heater_power` to the Mill cloud, which is the heater's **rated power**: the figure its
PID regulator uses to model the heater. It does not cap anything. Set it to 150 W on a 1500 W heater and the
heater keeps drawing ~1450 W, as a plug-in power meter will show.

The real limit is `limited_heating_power`, a percentage of the rated power. It is what the Mill app sets
under **PID controller → Adjust Wattage**, and the heater honours it within seconds. The underlying
library, [pymill](https://github.com/Danielhiversen/pymill), does not support it yet
([pymill#113](https://github.com/Danielhiversen/pymill/issues/113)).

## What this adds

- **Power limit** (`number`, W) — new. Writes `limited_heating_power` as a percentage of the rated power
  and reads it back the same way. Setting 600 W on a 1500 W heater sends 40 %.
- **Rated power** (`number`, W) — the existing entity, renamed so it is no longer mistaken for a limit.
  Leave it at the heater's nameplate power.
- After a power-limit change the library's 20-minute read cache is cleared, so the entity shows the new
  value at the next refresh instead of a stale one.

Everything else is Home Assistant's own code from release **2026.7.3**, unchanged.

## Install

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/Trikos/ha-mill`, type **Integration**.
2. Install **Mill (power limit fix)** and restart Home Assistant.
3. Your existing Mill config entry and entities are kept; a new *Power limit* entity appears on each heater.

Because the domain is `mill`, this overrides the built-in integration. Home Assistant logs a warning about
a custom integration replacing a core one; that is expected.

## Uninstall

Remove it from HACS and restart. The built-in integration takes over again; the *Power limit* entity
becomes unavailable and can be deleted.

Once `limited_heating_power` support lands in pymill and in Home Assistant core, this repository is no
longer needed.

## Tested on

- Home Assistant 2026.7.3, Mill cloud connection, 1500 W Mill heater with PID controller, power measured
  with a Shelly plug in front of it: a 300 W limit set from Home Assistant brought the draw from ~1000 W
  to 140–350 W (about 290 W on average) within a minute.
- The cloud reports a new limit only once the heater has picked it up. The entity shows the value you
  wrote for up to 10 minutes while that happens.

## License

Apache License 2.0, like Home Assistant core, from which this code is derived.
