/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Execute the production bit engine with scripted slave bits, never hardware. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "smbus.h"
#include "hardware/gpio.h"
#include "usb_commands.h"

static bool output[32], pulls[32], bits[1024];
static unsigned count, index_bit, driven_high, ends, closes;
static bool txbits[1024];
static unsigned txcount;
static int fault;
static uint64_t now;
uint sda_pin=7, scl_pin=6; /* EC mapping must stay untouched. */
uint64_t time_us_64(void) { return ++now; }
void busy_wait_us(uint64_t us) { now+=us; }
void gpio_init(uint pin) { output[pin]=false; }
void gpio_put(uint pin,bool value) { (void)pin; if(value) ++driven_high; }
void gpio_set_dir(uint pin,bool out) {
    if(pin==9 && !out && output[pin]) txbits[txcount++]=!output[7];
    output[pin]=out;
}
void gpio_pull_up(uint pin) { pulls[pin]=true; }
void gpio_disable_pulls(uint pin) { pulls[pin]=false; }
bool gpio_get(uint pin) {
    if(pin==9) return fault==1 ? false : fault==2 ? true : !output[pin];
    if(pin==7 && output[pin]) return fault==3;
    if(pin==7) { assert(index_bit<count); return bits[index_bit++]; }
    return false;
}
bool valid_pin(uint pin) { return pin<=22 || (pin>=26 && pin<=28); }
void dbgr_end_session(void) { ++ends; }
bool ene_close(void) { ++closes; return true; }
void bus_set_deadline(unsigned ms) { (void)ms; }
unsigned bus_timing(void) { return 5; }
const char *ec_capabilities(void) { return "CAPS SMBUS1"; }
unsigned ec_command_budget(const char *cmd) { (void)cmd; return 1000; }
bool ec_command(char *cmd) { (void)cmd; puts("EC_DISPATCH"); return true; }
static void bit(bool value) { bits[count++]=value; }
static void byte(unsigned value) { for(int i=7;i>=0;--i) bit((value>>i)&1); }
static unsigned crc(unsigned value,const unsigned *data,size_t n) {
    for(size_t i=0;i<n;++i) {
        value^=data[i];
        for(unsigned j=0;j<8;++j) value=((value<<1)^((value&128)?7:0))&255;
    }
    return value;
}
static void read_prefix(void) { bit(1);bit(0);bit(0);bit(1);bit(0); }
int main(int argc,char **argv) {
    if(argc<2) return 2;
    if(!strcmp(argv[1],"parser")) {
        char open[]="SMBOPEN 7 9 1 5";
        /* SMBOPEN's two idle-level samples. */
        bit(1);usb_command(open);
        for(int i=2;i<argc;++i) usb_command(argv[i]);
        printf("ENDS=%u CLOSES=%u ACTIVE=%u\n",ends,closes,smb_active());
        return 0;
    }
    assert(smb_open(7,9,true,5));
    uint16_t value=0xDEAD;bool ok=false;
    if(!strcmp(argv[1],"word") || !strcmp(argv[1],"badpec") || !strcmp(argv[1],"nopec")) {
        bool pec=strcmp(argv[1],"nopec")!=0;
        unsigned packet[]={0x16,9,0x17,0x51,0x3B};
        read_prefix();byte(0x51);byte(0x3B);
        if(pec) byte(crc(0,packet,5)^(!strcmp(argv[1],"badpec")?1:0));
        ok=smb_read_word(0x0B,9,pec,&value);
        printf("OK=%u VALUE=%04X ERROR=%s\n",ok,value,smb_error());
    } else if(!strcmp(argv[1],"block") || !strcmp(argv[1],"longblock") || !strcmp(argv[1],"mac34") || !strcmp(argv[1],"mac35")) {
        bool mac=!strncmp(argv[1],"mac",3);
        unsigned packet[38]={0x16,mac?0x44:0x20,0x17,3,'A','B','C'};
        uint8_t data[SMB_MAX_BLOCK];size_t len=99;
        read_prefix();byte(mac?(!strcmp(argv[1],"mac34")?34:35):!strcmp(argv[1],"longblock")?33:3);
        if(!strcmp(argv[1],"block")) { byte('A');byte('B');byte('C');byte(crc(0,packet,7)); }
        if(!strcmp(argv[1],"mac34")) {
            packet[3]=34;
            for(unsigned i=0;i<34;++i) { packet[4+i]=i;byte(i); }
            byte(crc(0,packet,38));
        }
        ok=smb_read_block(0x0B,mac?0x44:0x20,true,data,&len);
        printf("OK=%u LEN=%u ERROR=%s\n",ok,(unsigned)len,smb_error());
        if(ok && !mac) printf("DATA=%.*s\n",(int)len,data);
    } else if(!strcmp(argv[1],"nack")) {
        bit(1);bit(1);ok=smb_read_word(0x0B,9,true,&value);
        printf("OK=%u ERROR=%s\n",ok,smb_error());
    } else if(!strcmp(argv[1],"clocklow") || !strcmp(argv[1],"clockdrive") || !strcmp(argv[1],"datadrive")) {
        fault=!strcmp(argv[1],"clocklow")?1:!strcmp(argv[1],"clockdrive")?2:3;
        bit(1);ok=smb_read_word(0x0B,9,true,&value);
        printf("OK=%u ERROR=%s TIME=%llu\n",ok,smb_error(),(unsigned long long)now);
    } else if(!strcmp(argv[1],"write") || !strcmp(argv[1],"writeblock")) {
        bool block=!strcmp(argv[1],"writeblock");
        bit(1);for(unsigned i=0;i<(block?6u:5u);++i) bit(0);
        uint8_t data[]={1,0};
        ok=block?smb_write_block(0x0B,0x44,true,data,2):smb_write_word(0x0B,0,true,0x1234);
        printf("OK=%u ERROR=%s\n",ok,smb_error());
        printf("TX=");
        for(unsigned i=0;i+8<txcount;i+=9) {
            unsigned value=0;
            for(unsigned j=0;j<8;++j) value=(value<<1)|txbits[i+j];
            printf("%02X",value);
        }
        puts("");
    } else if(!strcmp(argv[1],"expire")) {
        now+=30000001;smb_tick();printf("ACTIVE=%u\n",smb_active());
    } else return 3;
    smb_close();
    printf("HIGH=%u RELEASED=%u PULLS=%u EC=%u,%u\n",driven_high,!output[7]&&!output[9],pulls[7]||pulls[9],sda_pin,scl_pin);
    return 0;
}
