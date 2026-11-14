/* SPDX-FileCopyrightText: 2026 R89 Repairs and contributors
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
/* Runs production ITE flash/session/parser code against a recording bus. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ite_bus.h"
#include "ite_dbgr.h"
#include "ite_flash.h"
#include "ene_edi.h"
#include "usb_commands.h"
#include "line_reader.h"
#include "device_runtime.h"

uint sda_pin=7, scl_pin=6;
const char *i2c_error;
unsigned wave_entry_rate;
static uint64_t now;
static unsigned writes, fail_at, timing=5;
static unsigned releases, ene_closes;
static bool ene_active;
#include "ite5_model.h"
/* This EC regression harness never enters the independent SMBus engine. */
bool smb_command(char *cmd) { (void)cmd; return false; }
bool smb_active(void) { return false; }
void smb_close(void) {}
void smb_tick(void) {}
uint64_t time_us_64(void) { return ++now; }
void sleep_us(uint64_t us) { now+=us; }
bool write_i2c(uint8_t address,const uint8_t *data,size_t count) {
    if (model_active) return model_write(address, data, count);
    printf("W %02X ",address);
    for (size_t i=0;i<count;++i) printf("%02X",data[i]);
    puts("");
    if (++writes == fail_at) { i2c_error="INJECTED_NACK"; return false; }
    return true;
}
bool read_i2c(uint8_t address,uint8_t *data,size_t count) {
    if (model_active) return model_read_bytes(address, data, count);
    printf("R %02X %u\n",address,(unsigned)count);
    for (size_t i=0;i<count;++i) data[i]=address==0x79 ? (uint8_t)i : 2;
    return true;
}
bool dbgr_reg_write(uint8_t reg,uint8_t value) {
    return ite_write_i2c(0x5a,&reg,1) && write_i2c(0x35,&value,1);
}
bool dbgr_reg_read(uint8_t reg,uint8_t *value) {
    return ite_write_i2c(0x5a,&reg,1) && read_i2c(0x35,value,1);
}
void release_bus(void) { ++releases; }
void release_pin(uint p) { (void)p; }
void low_pin(uint p) { (void)p; }
void set_pins(uint sda,uint scl) { sda_pin=sda; scl_pin=scl; }
bool valid_pin(uint p) { return p<=22 || (p>=26 && p<=28); }
bool adjacent_bus_pins(void) { return sda_pin+1==scl_pin || scl_pin+1==sda_pin; }
bool probe_write_address(uint8_t p) { (void)p; return true; }
void bus_set_deadline(unsigned ms) { (void)ms; }
bool bus_set_timing(unsigned us) { if(us!=5 && us!=3 && us!=2) return false; timing=us; return true; }
unsigned bus_timing(void) { return timing; }
void waveform(bool settle,unsigned frequency) { (void)settle; (void)frequency; }
void wave_at_power_on(void) {}
bool ene_open(uint8_t *hw,uint8_t *id) { *hw=0; *id=0; return false; }
bool ene_open_family(const char *family,uint8_t *hw,uint8_t *id) { (void)family; return ene_open(hw,id); }
bool ene_close(void) { ++ene_closes; ene_active=false; return true; }
bool ene_is_open(void) { return ene_active; }
bool ene_read_page(uint32_t a,uint8_t d[128]) { (void)a;(void)d;return false; }
bool ene_erase_page(uint32_t a) { (void)a;return false; }
bool ene_write_page(uint32_t a,const uint8_t d[128]) { (void)a;(void)d;return false; }
const char *ene_error(void) { return "SIMULATED"; }
const uint8_t *ene_last_rx(void) { static uint8_t d[36]; return d; }

int main(int argc,char **argv) {
    if(argc<2) return 2;
    if (!strcmp(argv[1], "model") && argc == 5) {
        model_cycle((uint32_t)strtoul(argv[2], NULL, 16),
                    (unsigned)strtoul(argv[3], NULL, 10), atoi(argv[4]) != 0);
        return 0;
    }
    uint8_t data[256];
    for(unsigned i=0;i<256;++i) data[i]=(uint8_t)i;
    dbgr_hold_until_us=30000000;
    dbgr_next_feed_us=1000000;
    if(!strcmp(argv[1],"hold")) {
        uint8_t initial=8;
        ite_write_i2c(0x5a,&initial,1);
        writes=0;
    }
    if(argc>2 && strcmp(argv[1],"command")) fail_at=(unsigned)atoi(argv[2]);
    if(!strcmp(argv[1],"legacy64")) program_flash_block(0x100,data,64);
    else if(!strcmp(argv[1],"legacy256")) program_flash_block(0x100,data,256);
    else if(!strcmp(argv[1],"v2_64")) program_flash_v2_block(0x100,data,64,false);
    else if(!strcmp(argv[1],"v2_256")) program_flash_v2_block(0x100,data,256,false);
    else if(!strcmp(argv[1],"page64")) program_flash_v2_block(0x100,data,64,true);
    else if(!strcmp(argv[1],"read")) read_flash_page(0x100);
    else if(!strcmp(argv[1],"hold")) {
        dbgr_next_feed_us=0;
        dbgr_hold_tick();
        uint8_t cursor;
        ite_selected_register(&cursor);
        printf("CURSOR=%02X HOLD=%u\n",cursor,dbgr_hold_until_us!=0);
    }
#ifndef BASELINE
    else if(!strcmp(argv[1],"erase1k")) erase_flash_sector(0x400,0xd7);
    else if(!strcmp(argv[1],"erase4k")) erase_flash_sector(0x1000,0x20);
    else if(!strcmp(argv[1],"command") && argc>2) usb_command(argv[2]);
    else if(!strcmp(argv[1],"eneactive") && argc>2) {
        ene_active=true;
        usb_command(argv[2]);
    }
    else if(!strcmp(argv[1],"cursor")) {
        uint8_t value=8, cursor;
        ite_write_i2c(0x5a,&value,1);
        value=9;
        write_i2c(0x5a,&value,1); /* Generic transfers have no ITE state. */
        ite_selected_register(&cursor);
        printf("GENERIC_CURSOR=%02X\n",cursor);
        fail_at=writes+1;
        ite_write_i2c(0x5a,&value,1);
        ite_selected_register(&cursor);
        printf("FAILED_CURSOR=%02X\n",cursor);
        fail_at=0;
        ite_set_pins(7,6);
        printf("SAME_PINS_VALID=%u\n",ite_selected_register(&cursor));
        ite_set_pins(9,8);
        printf("NEW_PINS_VALID=%u\n",ite_selected_register(&cursor));
    }
    else if(!strcmp(argv[1],"legacycursor")) {
        char select[]="WRITE 5A 08";
        usb_command(select);
        dbgr_next_feed_us=0;
        device_tick();
        uint8_t cursor;
        ite_selected_register(&cursor);
        printf("CURSOR=%02X HOLD=%u\n",cursor,dbgr_hold_until_us!=0);
    }
    else if(!strcmp(argv[1],"lifecycle")) {
        device_release();
        printf("RELEASE HOLD=%u BUS=%u ENE_CLOSE=%u\n",dbgr_hold_until_us!=0,releases,ene_closes);
        device_end_session();
        printf("END HOLD=%u BUS=%u ENE_CLOSE=%u\n",dbgr_hold_until_us!=0,releases,ene_closes);
    }
    else if(!strcmp(argv[1],"overflow")) {
        command_buffer buffer={0};
        for(unsigned i=0;i<MAX_LINE+5;++i) if(command_feed(&buffer,'X')<0) puts("OVERFLOW");
        const char *tail="WRITE 35 AD\nHELLO\n";
        for(const char *p=tail;*p;++p) if(command_feed(&buffer,*p)>0) usb_command(buffer.text);
    }
#endif
    else return 3;
    return 0;
}
