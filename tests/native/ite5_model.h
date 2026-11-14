/* Register-level ITE model: two/three-byte identities, SPI flash and WDT. */
#include <assert.h>
static bool model_active, model_expect_opcode, model_quick, model_halted;
static uint8_t model_regs[256], model_reg, model_opcode, model_status;
static uint32_t model_id, model_address, model_program_address;
static unsigned model_address_bytes, model_programmed, model_read, model_erased;
static uint8_t model_flash[ITE_FLASH_MAX_SIZE];
static bool model_kgd;

static void model_data(uint8_t value) {
    if (model_expect_opcode) {
        model_expect_opcode = false;
        model_opcode = value;
        model_address = 0;
        model_address_bytes = 0;
        if (value == 0x06) model_status = 2;
        if (value == 0x04) model_status = 0;
        return;
    }
    if (model_opcode != 0x0b && model_opcode != 0xad && model_opcode != 0x02 &&
        model_opcode != 0xd7 && model_opcode != 0x20) return;
    if (model_address_bytes < 3) {
        model_address = (model_address << 8) | value;
        if (++model_address_bytes == 3) {
            assert(model_address < ITE_FLASH_MAX_SIZE);
            model_program_address = model_address;
            if (model_opcode == 0xd7 || model_opcode == 0x20) {
                unsigned size = model_opcode == 0xd7 ? 1024 : 4096;
                assert(model_status == 2 && model_address % size == 0);
                memset(model_flash + model_address, 0xff, size);
                model_erased += size;
            }
        }
    } else if (model_opcode == 0xad || model_opcode == 0x02) {
        assert(model_status == 2 && model_program_address < ITE_FLASH_MAX_SIZE);
        model_flash[model_program_address++] &= value;
        ++model_programmed;
    }
}

static bool model_write(uint8_t address, const uint8_t *data, size_t count) {
    if (address == 0x5a) {
        assert(count == 1);
        model_reg = data[0];
    } else if (address == 0x35) {
        for (size_t i = 0; i < count; ++i) {
            uint8_t value = data[i];
            if (model_reg == 0x08) model_data(value);
            else {
                model_regs[model_reg] = value;
                if (model_reg == 0x05 && value == 0xfe) model_opcode = 0;
                if (model_reg == 0x05 && value == 0xfd) model_expect_opcode = true;
                if (model_reg == 0x10) model_quick = value == 0x20;
                if (model_reg == 0x27 && value == 0x81) model_halted = true;
                if (model_reg == 0x30 && model_id > 0xffff)
                    assert(model_regs[0x80] == 0xf0);
            }
        }
    } else if (address == 0x79) {
        assert(model_status == 2);
        assert(model_quick || model_opcode == 0x02);
        for (size_t i = 0; i < count; ++i) {
            assert(model_program_address < ITE_FLASH_MAX_SIZE);
            model_flash[model_program_address++] &= data[i];
            ++model_programmed;
        }
    } else assert(false);
    return true;
}

static bool model_read_bytes(uint8_t address, uint8_t *data, size_t count) {
    if (model_opcode == 0x9f && (address == 0x79 || count > 1)) {
        const uint8_t id[] = {0xff, 0xff, 0xfe};
        for (size_t i = 0; i < count; ++i) data[i] = model_kgd ? (i ? 0 : 0xc8) : id[i % 3];
    } else if (address == 0x79 && model_reg == 0x09) {
        assert(model_opcode == 0x0b && model_address + count <= ITE_FLASH_MAX_SIZE);
        memcpy(data, model_flash + model_address, count);
        model_address += count;
        model_read += count;
    } else {
        assert(address == 0x35 && count == 1);
        if (model_reg == 0x00) *data = (model_id >> 8) & 255;
        else if (model_reg == 0x01) *data = model_id & 255;
        else if (model_reg == 0x02) *data = 0x02;
        else if (model_reg == 0x30 && model_regs[0x2f] == 0x20 && model_regs[0x2e] == 0x85)
            *data = model_id >> 16;
        else if (model_reg == 0x30) *data = model_regs[0x30];
        else *data = model_status;
    }
    return true;
}

static void model_cycle(uint32_t id, unsigned size, bool kgd) {
    assert(size <= sizeof model_flash && size % 4096 == 0);
    model_active = true;
    model_id = id;
    model_kgd = kgd;
    memset(model_flash, 0xa5, sizeof model_flash);
    char family[] = "ITEFAMILY IT55XX";
    char entry[] = "ENTERDBGR";
    char session[] = "SESSION";
    usb_command(family);
    assert(!dbgr_hold_until_us);
    usb_command(session); /* An ID read cannot fabricate a held session. */
    usb_command(entry);
    assert(dbgr_hold_until_us && dbgr_extended == (id > 0xffff));
    assert(model_halted == (id > 0xffff));
    usb_command(session);
    uint32_t actual_id;
    uint8_t version;
    assert(dbgr_target_identity(&actual_id, &version) && actual_id == id && version == 2);
    flash_identify(0x79);
    for (unsigned address = 0; address < size; address += kgd ? 4096 : 1024)
        erase_flash_sector(address, kgd ? 0x20 : 0xd7);
    assert(model_erased == size);
    for (unsigned i = 0; i < sizeof model_flash; ++i)
        assert(model_flash[i] == (i < size ? 0xff : 0xa5));
    uint8_t data[256];
    unsigned count = kgd ? 64 : 256;
    for (unsigned address = 0; address < size; address += count) {
        for (unsigned i = 0; i < count; ++i) data[i] = (uint8_t)((address + i) ^ ((address + i) >> 16));
        program_flash_v2_block(address, data, count, kgd);
    }
    assert(model_programmed == size);
    for (unsigned i = 0; i < size; ++i)
        assert(model_flash[i] == (uint8_t)(i ^ (i >> 16)));
    for (unsigned address = 0; address < size; address += 256) read_flash_page(address);
    assert(model_read == size);
    assert(!model_quick);
    puts("ITE5_FULL_CYCLE_OK");
}
