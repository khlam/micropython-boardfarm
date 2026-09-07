// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// `_matter` exposes protocol primitives only. The frozen `matter` package owns
// endpoint state, event routing, and every application decision.
#include "matter/bridge.h"

#include <errno.h>
#include <string.h>

#include "py/obj.h"
#include "py/runtime.h"

// How long a call blocks the VM task waiting on the CHIP task. Long enough to
// absorb a busy stack, short enough that a stalled one surfaces as OSError
// instead of wedging the MicroPython scheduler.
#define MATTER_REQUEST_TIMEOUT_MS (250)

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

// Publish a locally decided batch, taking
// (endpoint_id, ((cluster, attribute, value), ...)) positionally.
static mp_obj_t attributes_publish(mp_obj_t endpoint_id_in, mp_obj_t updates_in)
{
    size_t count = 0;
    mp_obj_t *items = NULL;
    mp_obj_get_array(updates_in, &count, &items);
    if (count == 0 || count > MATTER_MAX_ATTRIBUTE_BATCH) {
        mp_raise_ValueError(MP_ERROR_TEXT("attribute batch size is out of range"));
    }
    struct matter_attribute_update updates[MATTER_MAX_ATTRIBUTE_BATCH];
    for (size_t index = 0; index < count; ++index) {
        size_t field_count = 0;
        mp_obj_t *fields = NULL;
        mp_obj_get_array(items[index], &field_count, &fields);
        if (field_count != 3) {
            mp_raise_ValueError(MP_ERROR_TEXT("attribute update must have three fields"));
        }
        updates[index].cluster_id = mp_obj_get_int(fields[0]);
        updates[index].attribute_id = mp_obj_get_int(fields[1]);
        updates[index].value = value_from_object(fields[2], &updates[index].value_type);
    }
    check(matter_attributes_publish((uint16_t)mp_obj_get_int(endpoint_id_in), updates, count,
                                    MATTER_REQUEST_TIMEOUT_MS));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(attributes_publish_obj, attributes_publish);

// Return the current native state generation without entering the CHIP task.
static mp_obj_t generation(void)
{
    return mp_obj_new_int_from_uint(matter_state_generation());
}
static MP_DEFINE_CONST_FUN_OBJ_0(generation_obj, generation);

// Return (captured_generation, records), where every record is
// (revision, kind, endpoint_id, cluster, attribute, value). The bridge copies
// into request-owned memory first, so a timeout cannot leave CHIP writing into
// this MicroPython-owned buffer after the function raises.
static mp_obj_t snapshot(void)
{
    struct matter_snapshot_record *native_records =
        m_new(struct matter_snapshot_record, MATTER_MAX_SNAPSHOT_RECORDS);
    size_t count = 0;
    uint32_t captured_generation = 0;
    check(matter_get_state_snapshot(native_records, MATTER_MAX_SNAPSHOT_RECORDS, &count,
                                    &captured_generation, MATTER_REQUEST_TIMEOUT_MS));
    mp_obj_t *record_objects = m_new(mp_obj_t, count);
    for (size_t index = 0; index < count; ++index) {
        const struct matter_snapshot_record *record = &native_records[index];
        mp_obj_t fields[6] = {
            mp_obj_new_int_from_uint(record->revision),
            MP_OBJ_NEW_SMALL_INT(record->kind),
            mp_obj_new_int_from_uint(record->endpoint_id),
            mp_obj_new_int_from_uint(record->cluster_id),
            mp_obj_new_int_from_uint(record->attribute_id),
            value_to_object(record->value, record->value_type),
        };
        record_objects[index] = mp_obj_new_tuple(6, fields);
    }
    mp_obj_t records = mp_obj_new_tuple(count, record_objects);
    m_del(mp_obj_t, record_objects, count);
    m_del(struct matter_snapshot_record, native_records, MATTER_MAX_SNAPSHOT_RECORDS);
    mp_obj_t result[2] = {mp_obj_new_int_from_uint(captured_generation), records};
    return mp_obj_new_tuple(2, result);
}
static MP_DEFINE_CONST_FUN_OBJ_0(snapshot_obj, snapshot);

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

// Report the station address, or None while the device is not on the network.
//
// Not being on the network yet is an ordinary state on the way up, not a
// failure, so ENOTCONN becomes None rather than an OSError a caller would have
// to catch on every poll. Every other errno still raises.
static mp_obj_t network_address(void)
{
    char address[MATTER_ADDRESS_SIZE];
    const int error = matter_network_address(address, sizeof(address));
    if (error == ENOTCONN) {
        return mp_const_none;
    }
    check(error);
    return mp_obj_new_str(address, strlen(address));
}
static MP_DEFINE_CONST_FUN_OBJ_0(network_address_obj, network_address);

// The whole `_matter` surface. Anything not named here is unreachable from
// Python, which is what keeps the frozen package the only public API.
static const mp_rom_map_elem_t native_module_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__matter)},
    {MP_ROM_QSTR(MP_QSTR_node_create), MP_ROM_PTR(&node_create_obj)},
    {MP_ROM_QSTR(MP_QSTR_endpoint_create), MP_ROM_PTR(&endpoint_create_obj)},
    {MP_ROM_QSTR(MP_QSTR_attribute_set_initial), MP_ROM_PTR(&attribute_set_initial_obj)},
    {MP_ROM_QSTR(MP_QSTR_start), MP_ROM_PTR(&stack_start_obj)},
    {MP_ROM_QSTR(MP_QSTR_attribute_get), MP_ROM_PTR(&attribute_get_obj)},
    {MP_ROM_QSTR(MP_QSTR_attributes_publish), MP_ROM_PTR(&attributes_publish_obj)},
    {MP_ROM_QSTR(MP_QSTR_generation), MP_ROM_PTR(&generation_obj)},
    {MP_ROM_QSTR(MP_QSTR_snapshot), MP_ROM_PTR(&snapshot_obj)},
    {MP_ROM_QSTR(MP_QSTR_open_commissioning_window), MP_ROM_PTR(&open_commissioning_window_obj)},
    {MP_ROM_QSTR(MP_QSTR_fabrics), MP_ROM_PTR(&fabrics_obj)},
    {MP_ROM_QSTR(MP_QSTR_remove_fabric), MP_ROM_PTR(&remove_fabric_obj)},
    {MP_ROM_QSTR(MP_QSTR_factory_reset), MP_ROM_PTR(&factory_reset_obj)},
    {MP_ROM_QSTR(MP_QSTR_network_address), MP_ROM_PTR(&network_address_obj)},
};
static MP_DEFINE_CONST_DICT(native_module_globals, native_module_globals_table);

const mp_obj_module_t native_module = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&native_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR__matter, native_module);
