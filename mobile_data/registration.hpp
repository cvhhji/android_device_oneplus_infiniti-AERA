/* SPDX-License-Identifier: Apache-2.0 */
#pragma once
#include "qmi.hpp"

namespace aera::mobile {
struct Registration {
  bool registered=false;
  std::string technology;
  bool legacy_attached=false,lte_packet=false,nr_packet=false;
};

inline bool PacketService(const Values &info,uint8_t service_tag,uint8_t system_tag) {
  const auto &service=Field(info,service_tag),&system=Field(info,system_tag);
  // Service available plus a valid PS domain, not just a detectable cell or
  // a stored signal measurement. The first eight system-info bytes are common
  // to the GSM/WCDMA/LTE/TD-SCDMA/NR response structures.
  return service.size()>=3&&service[0]==2&&system.size()>=8&&system[0]==1&&
      (system[1]==2||system[1]==3)&&!(system[6]==1&&system[7]!=0);
}

inline Registration ParseRegistration(const Values &serving,const Values &info) {
  Registration result;
  const auto &legacy=Field(serving,1);
  if(legacy.size()>=5&&legacy[4]<=legacy.size()-5) {
    result.legacy_attached=legacy[0]==1&&legacy[2]==1;
    if(result.legacy_attached) {
      for(size_t i=5;i<5u+legacy[4];++i) {
        switch(legacy[i]) {
          case 4:if(result.technology.empty())result.technology="2G";break;
          case 5:case 9:if(result.technology!="4G"&&result.technology!="5G")result.technology="3G";break;
          case 8:if(result.technology!="5G")result.technology="4G";break;
          case 12:result.technology="5G";break;
          default:break;
        }
      }
    }
  }
  const bool gsm=PacketService(info,0x12,0x17),wcdma=PacketService(info,0x13,0x18);
  const bool tdscdma=PacketService(info,0x24,0x25);
  result.lte_packet=PacketService(info,0x14,0x19);
  // Get System Info RESPONSE tags: NR service=0x4a, NR system=0x4b.
  // The indication has different tags and must not be decoded as this reply.
  result.nr_packet=PacketService(info,0x4a,0x4b);
  result.registered=result.legacy_attached||gsm||wcdma||tdscdma||result.lte_packet||result.nr_packet;
  if(gsm&&result.technology.empty())result.technology="2G";
  if((wcdma||tdscdma)&&result.technology!="4G"&&result.technology!="5G")result.technology="3G";
  if(result.lte_packet&&result.technology!="5G")result.technology="4G";
  const auto &nr=Field(info,0x4a);
  if(result.registered&&nr.size()>=3&&nr[0]==2&&
      (nr[2]==1||(result.nr_packet&&!result.lte_packet&&!result.legacy_attached)))
    result.technology="5G";
  return result;
}

inline bool ValidApn(const std::string &apn) {
  return !apn.empty()&&apn.size()<=100&&
      apn.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")==std::string::npos;
}
}
