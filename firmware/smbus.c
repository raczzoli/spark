/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Separate SMBus engine: preserves the validated EC bus and its timings. */
#include "smbus.h"
#include "i2c_bus.h"
#include "hardware/gpio.h"

static bool active;
static uint data_pin, clock_pin;
static unsigned delay = 5;
static uint64_t deadline, expires;
static const char *error;

static void high(uint pin) { gpio_set_dir(pin, GPIO_IN); }
static void low(uint pin) { gpio_put(pin, 0); gpio_set_dir(pin, GPIO_OUT); }
static void pause_bus(void) { busy_wait_us(delay); }
static bool fail(const char *reason) { if (!error) error = reason; return false; }
static bool scl_high(void) {
    high(clock_pin);
    uint64_t limit = time_us_64() + 35000;
    while (!gpio_get(clock_pin)) {
        if (time_us_64() >= limit) return fail("SMB_CLOCK_TIMEOUT");
        if (time_us_64() >= deadline) return fail("SMB_TIMEOUT");
    }
    pause_bus();
    return true;
}
static bool start(void) {
    high(data_pin); pause_bus();
    if (!scl_high()) return false;
    if (!gpio_get(data_pin)) return fail("SMB_DATA_LOW");
    low(data_pin); pause_bus();
    if (gpio_get(data_pin)) return fail("SMB_DATA_DRIVE");
    low(clock_pin); pause_bus();
    if (gpio_get(clock_pin)) return fail("SMB_CLOCK_DRIVE");
    return true;
}
static void stop(void) {
    low(clock_pin); low(data_pin); pause_bus();
    if (scl_high()) { high(data_pin); pause_bus(); }
    high(clock_pin); high(data_pin);
}
static bool out_bit(bool value) {
    if (time_us_64() >= deadline) return fail("SMB_TIMEOUT");
    if (value) high(data_pin); else low(data_pin);
    pause_bus();
    if (!scl_high()) return false;
    low(clock_pin); pause_bus(); return true;
}
static bool in_bit(bool *value) {
    high(data_pin); pause_bus();
    if (!scl_high()) return false;
    *value = gpio_get(data_pin);
    low(clock_pin); pause_bus(); return true;
}
static bool out_byte(uint8_t value, const char *nack) {
    for (int i=7;i>=0;--i) if (!out_bit((value >> i) & 1u)) return false;
    bool bit;
    return in_bit(&bit) && (!bit || fail(nack));
}
static bool in_byte(uint8_t *value, bool ack) {
    *value=0;
    for (unsigned i=0;i<8;++i) {
        bool bit;
        if (!in_bit(&bit)) return false;
        *value=(uint8_t)((*value << 1) | bit);
    }
    return out_bit(!ack);
}
static uint8_t crc_byte(uint8_t crc,uint8_t value) {
    crc ^= value;
    for (unsigned i=0;i<8;++i) crc=(uint8_t)((crc << 1) ^ ((crc & 0x80) ? 7 : 0));
    return crc;
}
static bool begin(uint8_t addr,uint8_t reg,uint8_t *crc) {
    error=NULL;
    if (!active) return fail("SMB_NOT_OPEN");
    deadline=time_us_64()+1000000;
    expires=time_us_64()+30000000;
    *crc=crc_byte(crc_byte(0,addr << 1),reg);
    return start() && out_byte(addr << 1,"SMB_ADDRESS_NACK") && out_byte(reg,"SMB_COMMAND_NACK");
}
static bool begin_read(uint8_t addr,uint8_t reg,uint8_t *crc) {
    if (!begin(addr,reg,crc)) return false;
    *crc=crc_byte(*crc,(addr << 1)|1);
    return start() && out_byte((addr << 1)|1,"SMB_READ_NACK");
}
bool smb_open(uint sda,uint scl,bool pullups,unsigned delay_us) {
    error=NULL;
    if (!valid_pin(sda) || !valid_pin(scl) || sda==scl || (delay_us!=5 && delay_us!=10))
        return fail("SMB_ARGUMENT");
    smb_close();
    data_pin=sda;clock_pin=scl;delay=delay_us;
    gpio_init(data_pin);gpio_init(clock_pin);
    gpio_put(data_pin,0);gpio_put(clock_pin,0);
    high(data_pin);high(clock_pin);
    if (pullups) { gpio_pull_up(data_pin);gpio_pull_up(clock_pin); }
    else { gpio_disable_pulls(data_pin);gpio_disable_pulls(clock_pin); }
    active=true;error=NULL;expires=time_us_64()+30000000;
    busy_wait_us(2000);
    return true;
}
bool smb_active(void) { return active; }
void smb_close(void) {
    if (!active) return;
    high(data_pin);high(clock_pin);
    gpio_disable_pulls(data_pin);gpio_disable_pulls(clock_pin);
    active=false;
}
void smb_tick(void) { if (active && time_us_64() >= expires) smb_close(); }
void smb_levels(bool *sda,bool *scl) {
    *sda=active && gpio_get(data_pin);*scl=active && gpio_get(clock_pin);
}
const char *smb_error(void) { return error ? error : "SMB_BUS"; }
bool smb_read_word(uint8_t addr,uint8_t reg,bool pec,uint16_t *value) {
    uint8_t crc=0,lo=0,hi=0,received=0;
    if (!active) return fail("SMB_NOT_OPEN");
    bool ok=begin_read(addr,reg,&crc);
    if (ok) ok=in_byte(&lo,true) && in_byte(&hi,pec);
    crc=crc_byte(crc_byte(crc,lo),hi);
    if (ok && pec) ok=in_byte(&received,false) && (received==crc || fail("SMB_PEC"));
    stop();
    if (error) ok=false;
    if (ok) *value=(uint16_t)lo|((uint16_t)hi << 8);
    return ok;
}
bool smb_read_block(uint8_t addr,uint8_t reg,bool pec,uint8_t data[SMB_MAX_BLOCK],size_t *len) {
    uint8_t crc=0,count=0,received=0;
    if (!active) return fail("SMB_NOT_OPEN");
    bool ok=begin_read(addr,reg,&crc);
    if (ok) ok=in_byte(&count,true);
    /* Standard SBS blocks stay at 32; MAC register 44 allows its echo prefix. */
    if (ok && (count<1 || count>(reg==0x44 ? SMB_MAX_BLOCK : 32))) ok=fail("SMB_BLOCK_LENGTH");
    crc=crc_byte(crc,count);
    for (unsigned i=0;ok && i<count;++i) {
        ok=in_byte(&data[i],pec || i+1<count);
        if (ok) crc=crc_byte(crc,data[i]);
    }
    if (ok && pec) ok=in_byte(&received,false) && (received==crc || fail("SMB_PEC"));
    stop();
    if (error) ok=false;
    if (ok) *len=count;
    return ok;
}
bool smb_write_word(uint8_t addr,uint8_t reg,bool pec,uint16_t value) {
    uint8_t crc=0,lo=value&255,hi=value >> 8;
    if (!active) return fail("SMB_NOT_OPEN");
    bool ok=begin(addr,reg,&crc) && out_byte(lo,"SMB_DATA_NACK") && out_byte(hi,"SMB_DATA_NACK");
    crc=crc_byte(crc_byte(crc,lo),hi);
    if (ok && pec) ok=out_byte(crc,"SMB_PEC_NACK");
    stop();return ok && !error;
}
bool smb_write_block(uint8_t addr,uint8_t reg,bool pec,const uint8_t *data,size_t len) {
    uint8_t crc=0;
    if (!active) return fail("SMB_NOT_OPEN");
    if (len<1 || len>32) return fail("SMB_BLOCK_LENGTH");
    bool ok=begin(addr,reg,&crc) && out_byte((uint8_t)len,"SMB_DATA_NACK");
    crc=crc_byte(crc,(uint8_t)len);
    for (size_t i=0;ok && i<len;++i) {
        ok=out_byte(data[i],"SMB_DATA_NACK");crc=crc_byte(crc,data[i]);
    }
    if (ok && pec) ok=out_byte(crc,"SMB_PEC_NACK");
    stop();return ok && !error;
}
