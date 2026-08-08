// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// `_matter` exposes protocol primitives only. The frozen `matter` package owns
// endpoint state, callback routing, and every application decision.
#include "matter/bridge.h"

#include <string.h>

#include "py/obj.h"
#include "py/runtime.h"

// A root pointer, not a plain static: the callback is the only reference to a
// Python object held across VM calls, so the GC has to trace it.
MP_REGISTER_ROOT_POINTER(mp_obj_t matter_event_callback);

// How long a call blocks the VM task waiting on the CHIP task. Long enough to
// absorb a busy stack, short enough that a stalled one surfaces as OSError
// instead of wedging the MicroPython scheduler.
#define MATTER_REQUEST_TIMEOUT_MS (250)

static mp_sched_node_t matter_event_node;

// Narrow a Python value into the tagged uint32 the bridge carries.
//
// bool is checked first because it is an integer subtype in Python while the
// two are distinct attribute types in Matter. The width tag is only a hint at
// how small the value is: what actually fits is decided by the attribute's own
// stored type, which is known on the stack side, so an integer too wide for its
// tag is refused there rather than truncated here.
static uint32_t value_from_object(mp_obj_t input, uint8_t *value_type)
{
    if (mp_obj_is_bool(input)) {
        *value_type = MATTER_VALUE_BOOL;
        return mp_obj_is_true(input) ? 1U : 0U;
    }
    const mp_int_t value = mp_obj_get_int(input);
    if (value < 0 || (uint64_t)value > UINT32_MAX) {
        mp_raise_ValueError(MP_ERROR_TEXT("attribute value is out of range"));
    }
    *value_type = value <= UINT8_MAX ? MATTER_VALUE_UINT8 : MATTER_VALUE_UINT16;
    return (uint32_t)value;
}

// Turn a non-zero bridge errno into the OSError Python expects.
//
// Every bridge call reports failure the same way, so every entry point below
// funnels through here rather than repeating the test. Named after the port's
// own check_esp_err(), which does this for esp_err_t.
static void check(int error)
{
    if (error != 0) {
        mp_raise_OSError(error);
    }
}

// Rebuild a tagged bridge value as the Python type it came from, so an OnOff
// read returns True rather than 1.
static mp_obj_t value_to_object(uint32_t value, uint8_t value_type)
{
    if (value_type == MATTER_VALUE_BOOL) {
        return mp_obj_new_bool(value != 0U);
    }
    return mp_obj_new_int_from_uint(value);
}

// Unpack the (endpoint_id, cluster, attribute) triple every attribute call
// takes as its first three positional arguments.
static void unpack_path(const mp_obj_t *arguments, uint16_t *endpoint_id, uint32_t *cluster_id,
                        uint32_t *attribute_id)
{
    *endpoint_id = (uint16_t)mp_obj_get_int(arguments[0]);
    *cluster_id = mp_obj_get_int(arguments[1]);
    *attribute_id = mp_obj_get_int(arguments[2]);
}

// The module functions below convert objects and raise; they validate nothing
// beyond what a conversion forces, because the frozen `matter` package owns
// every application rule. A non-zero errno from the bridge becomes OSError, so
// Python sees a failure as an exception rather than a return code.

// Create the sole Matter node.
static mp_obj_t node_create(void)
{
    check(matter_node_create());
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(node_create_obj, node_create);

// Add one endpoint of the given type and return the ID the stack assigned.
static mp_obj_t endpoint_create(mp_obj_t endpoint_type_in)
{
    uint16_t endpoint_id = 0;
    check(matter_endpoint_create((uint8_t)mp_obj_get_int(endpoint_type_in), &endpoint_id));
    return mp_obj_new_int_from_uint(endpoint_id);
}
static MP_DEFINE_CONST_FUN_OBJ_1(endpoint_create_obj, endpoint_create);

// Seed one attribute before the stack starts, taking
// (endpoint_id, cluster, attribute, value) positionally.
static mp_obj_t attribute_set_initial(size_t argument_count, const mp_obj_t *arguments)
{
    (void)argument_count;
    uint16_t endpoint_id;
    uint32_t cluster_id;
    uint32_t attribute_id;
    unpack_path(arguments, &endpoint_id, &cluster_id, &attribute_id);
    uint8_t value_type = 0;
    const uint32_t value = value_from_object(arguments[3], &value_type);
    check(matter_attribute_set_initial(endpoint_id, cluster_id, attribute_id, value, value_type));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(attribute_set_initial_obj, 4, 4, attribute_set_initial);

// Bring CHIP up, exported as `start`. Endpoints are fixed once this returns.
static mp_obj_t stack_start(void)
{
    check(matter_stack_start());
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(stack_start_obj, stack_start);

// Read one attribute from the running stack, taking
// (endpoint_id, cluster, attribute) positionally and blocking the VM task for
// at most MATTER_REQUEST_TIMEOUT_MS.
static mp_obj_t attribute_get(size_t argument_count, const mp_obj_t *arguments)
{
    (void)argument_count;
    uint16_t endpoint_id;
    uint32_t cluster_id;
    uint32_t attribute_id;
    unpack_path(arguments, &endpoint_id, &cluster_id, &attribute_id);
    uint32_t value = 0;
    uint8_t value_type = 0;
    check(matter_attribute_get(endpoint_id, cluster_id, attribute_id, &value, &value_type,
                               MATTER_REQUEST_TIMEOUT_MS));
    return value_to_object(value, value_type);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(attribute_get_obj, 3, 3, attribute_get);

// Publish a locally decided value, taking
// (endpoint_id, cluster, attribute, value) positionally.
static mp_obj_t attribute_publish(size_t argument_count, const mp_obj_t *arguments)
{
    (void)argument_count;
    uint16_t endpoint_id;
    uint32_t cluster_id;
    uint32_t attribute_id;
    unpack_path(arguments, &endpoint_id, &cluster_id, &attribute_id);
    uint8_t value_type = 0;
    const uint32_t value = value_from_object(arguments[3], &value_type);
    check(matter_attribute_publish(endpoint_id, cluster_id, attribute_id, value, value_type,
                                   MATTER_REQUEST_TIMEOUT_MS));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(attribute_publish_obj, 4, 4, attribute_publish);

// Pop one queued event as
// (kind, endpoint_id, cluster, attribute, value, origin), or None when the
// queue is dry. Never waits, so the drain loop can run to exhaustion on the VM
// task without blocking it.
static mp_obj_t next_event(void)
{
    struct matter_event event;
    if (!matter_next_event(&event)) {
        return mp_const_none;
    }
    mp_obj_t items[6] = {
        MP_OBJ_NEW_SMALL_INT(event.kind),
        mp_obj_new_int_from_uint(event.endpoint_id),
        mp_obj_new_int_from_uint(event.cluster_id),
        mp_obj_new_int_from_uint(event.attribute_id),
        value_to_object(event.value, event.value_type),
        MP_OBJ_NEW_SMALL_INT(event.origin),
    };
    return mp_obj_new_tuple(6, items);
}
static MP_DEFINE_CONST_FUN_OBJ_0(next_event_obj, next_event);

// Report whether the queue dropped an event since the last call, consuming the
// flag so one overflow costs one resynchronization.
static mp_obj_t overflowed(void)
{
    return mp_obj_new_bool(matter_take_overflow());
}
static MP_DEFINE_CONST_FUN_OBJ_0(overflowed_obj, overflowed);

// Register the drain callback the stack schedules onto the VM task, or clear it
// with None. Callability is checked here so a bad argument fails at
// registration instead of inside a scheduled callback that has no caller left
// to raise into.
static mp_obj_t on_event(mp_obj_t callback)
{
    if (callback != mp_const_none && !mp_obj_is_callable(callback)) {
        mp_raise_TypeError(MP_ERROR_TEXT("callback must be callable or None"));
    }
    MP_STATE_PORT(matter_event_callback) = callback;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(on_event_obj, on_event);

// Reopen pairing for the given number of seconds.
static mp_obj_t open_commissioning_window(mp_obj_t timeout_in)
{
    check(matter_open_commissioning_window((uint16_t)mp_obj_get_int(timeout_in), MATTER_REQUEST_TIMEOUT_MS));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(open_commissioning_window_obj, open_commissioning_window);

// Return one (index, fabric_id, node_id, vendor_id, label) tuple per
// commissioned fabric. The native records are staged on the stack, which the
// MATTER_MAX_FABRICS ceiling is what makes possible.
static mp_obj_t fabrics(void)
{
    struct matter_fabric native_fabrics[MATTER_MAX_FABRICS];
    size_t count = 0;
    check(matter_get_fabrics(native_fabrics, MATTER_MAX_FABRICS, &count, MATTER_REQUEST_TIMEOUT_MS));
    mp_obj_t items[MATTER_MAX_FABRICS];
    for (size_t index = 0; index < count; ++index) {
        const struct matter_fabric *fabric = &native_fabrics[index];
        mp_obj_t fields[5] = {
            mp_obj_new_int_from_uint(fabric->index),
            mp_obj_new_int_from_ull(fabric->fabric_id),
            mp_obj_new_int_from_ull(fabric->node_id),
            mp_obj_new_int_from_uint(fabric->vendor_id),
            mp_obj_new_str(fabric->label, strlen(fabric->label)),
        };
        items[index] = mp_obj_new_tuple(5, fields);
    }
    return mp_obj_new_tuple(count, items);
}
static MP_DEFINE_CONST_FUN_OBJ_0(fabrics_obj, fabrics);

// Drop one fabric by its operational index.
static mp_obj_t remove_fabric(mp_obj_t index_in)
{
    check(matter_remove_fabric((uint8_t)mp_obj_get_int(index_in), MATTER_REQUEST_TIMEOUT_MS));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(remove_fabric_obj, remove_fabric);

// Ask CHIP to erase persisted state and reboot. Returning is not proof the
// reboot happened, only that the request was accepted.
static mp_obj_t factory_reset(void)
{
    check(matter_factory_reset(MATTER_REQUEST_TIMEOUT_MS));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(factory_reset_obj, factory_reset);

// The whole `_matter` surface. Anything not named here is unreachable from
// Python, which is what keeps the frozen package the only public API.
static const mp_rom_map_elem_t native_module_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__matter)},
    {MP_ROM_QSTR(MP_QSTR_node_create), MP_ROM_PTR(&node_create_obj)},
    {MP_ROM_QSTR(MP_QSTR_endpoint_create), MP_ROM_PTR(&endpoint_create_obj)},
    {MP_ROM_QSTR(MP_QSTR_attribute_set_initial), MP_ROM_PTR(&attribute_set_initial_obj)},
    {MP_ROM_QSTR(MP_QSTR_start), MP_ROM_PTR(&stack_start_obj)},
    {MP_ROM_QSTR(MP_QSTR_attribute_get), MP_ROM_PTR(&attribute_get_obj)},
    {MP_ROM_QSTR(MP_QSTR_attribute_publish), MP_ROM_PTR(&attribute_publish_obj)},
    {MP_ROM_QSTR(MP_QSTR_next_event), MP_ROM_PTR(&next_event_obj)},
    {MP_ROM_QSTR(MP_QSTR_overflowed), MP_ROM_PTR(&overflowed_obj)},
    {MP_ROM_QSTR(MP_QSTR_on_event), MP_ROM_PTR(&on_event_obj)},
    {MP_ROM_QSTR(MP_QSTR_open_commissioning_window), MP_ROM_PTR(&open_commissioning_window_obj)},
    {MP_ROM_QSTR(MP_QSTR_fabrics), MP_ROM_PTR(&fabrics_obj)},
    {MP_ROM_QSTR(MP_QSTR_remove_fabric), MP_ROM_PTR(&remove_fabric_obj)},
    {MP_ROM_QSTR(MP_QSTR_factory_reset), MP_ROM_PTR(&factory_reset_obj)},
};
static MP_DEFINE_CONST_DICT(native_module_globals, native_module_globals_table);

const mp_obj_module_t native_module = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&native_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR__matter, native_module);

// Run the registered drain callback on the VM task.
//
// nlr_push contains a raising callback: this frame is entered by the scheduler,
// so an escaping exception has no caller to reach and would tear down the VM.
// The report goes out as compact JSON because every line this firmware prints
// is parsed as JSON; a bare message would be dropped by the reader.
static void dispatch_event(mp_sched_node_t *node)
{
    (void)node;
    const mp_obj_t callback = MP_STATE_PORT(matter_event_callback);
    if (callback == MP_OBJ_NULL || callback == mp_const_none) {
        return;
    }
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_call_function_0(callback);
        nlr_pop();
    } else {
        mp_printf(&mp_plat_print,
                  "{\"event\":\"error\",\"component\":\"python_callback\","
                  "\"message\":\"callback raised an exception\"}\n");
    }
}

// Wake the drain from whichever task enqueued an event.
//
// Scheduling a node is safe from a CHIP task or an interrupt, and repeat
// notifications collapse into the one pending node — which is why the Python
// side drains in a loop rather than expecting one wake per event.
void matter_bridge_notify_event(void)
{
    mp_sched_schedule_node(&matter_event_node, dispatch_event);
}
