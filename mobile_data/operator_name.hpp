/* SPDX-License-Identifier: Apache-2.0 */
#pragma once
#include "qmi.hpp"
#include "registration.hpp"

namespace aera::mobile {
inline bool OperatorScalar(uint32_t c) {
  return c>=0x20&&c<=0x10ffff&&!(c>=0x7f&&c<=0x9f)&&
      !(c>=0xd800&&c<=0xdfff)&&!(c>=0xfdd0&&c<=0xfdef)&&
      (c&0xffff)<0xfffe&&c!=0xfffd;
}
inline bool AppendOperatorScalar(std::string &out,uint32_t c) {
  if(!OperatorScalar(c))return false;
  if(c<0x80)out.push_back(static_cast<char>(c));
  else if(c<0x800) {
    out.push_back(static_cast<char>(0xc0|(c>>6)));
    out.push_back(static_cast<char>(0x80|(c&0x3f)));
  }else if(c<0x10000) {
    out.push_back(static_cast<char>(0xe0|(c>>12)));
    out.push_back(static_cast<char>(0x80|((c>>6)&0x3f)));
    out.push_back(static_cast<char>(0x80|(c&0x3f)));
  }else {
    out.push_back(static_cast<char>(0xf0|(c>>18)));
    out.push_back(static_cast<char>(0x80|((c>>12)&0x3f)));
    out.push_back(static_cast<char>(0x80|((c>>6)&0x3f)));
    out.push_back(static_cast<char>(0x80|(c&0x3f)));
  }
  return true;
}
inline std::string OperatorUtf8(const Bytes &bytes) {
  if(bytes.empty()||bytes.size()>512)return {};
  std::string out;
  for(size_t i=0;i<bytes.size();) {
    uint32_t c=bytes[i++],minimum=0;unsigned remaining=0;
    if(c>=0xc2&&c<=0xdf){remaining=1;minimum=0x80;c&=0x1f;}
    else if(c>=0xe0&&c<=0xef){remaining=2;minimum=0x800;c&=0x0f;}
    else if(c>=0xf0&&c<=0xf4){remaining=3;minimum=0x10000;c&=7;}
    else if(c>=0x80)return {};
    if(remaining>bytes.size()-i)return {};
    for(unsigned j=0;j<remaining;++j) {
      const auto next=bytes[i++];if((next&0xc0)!=0x80)return {};
      c=(c<<6)|(next&0x3f);
    }
    if(c<minimum||!AppendOperatorScalar(out,c))return {};
  }
  return out;
}
inline std::string OperatorUtf16Le(const Bytes &bytes) {
  if(bytes.empty()||bytes.size()>512||bytes.size()%2)return {};
  std::string out;
  for(size_t i=0;i<bytes.size();i+=2) {
    uint32_t c=U16(&bytes[i]);
    if(i==0&&c==0xfeff)continue;
    if(c==0) {
      // Accept a modem's trailing terminator, never an embedded control.
      for(size_t j=i;j<bytes.size();++j)if(bytes[j])return {};
      break;
    }
    if(c>=0xd800&&c<=0xdbff) {
      if(bytes.size()-i<4)return {};
      const uint32_t low=U16(&bytes[i+2]);
      if(low<0xdc00||low>0xdfff)return {};
      c=0x10000+((c-0xd800)<<10)+(low-0xdc00);i+=2;
    }
    if(!AppendOperatorScalar(out,c))return {};
  }
  return out;
}
inline std::string DecodeOperatorText(const Bytes &name) {
  Bytes utf8_name=name;
  while(!utf8_name.empty()&&utf8_name.back()==0)utf8_name.pop_back();
  const auto utf8=OperatorUtf8(utf8_name);
  if(!utf8.empty())return utf8;
  // NAS Serving System declares an ASCII description without an encoding
  // byte. This modem returns UCS-2LE here. Decode before JSON serialization,
  // where invalid UTF-8 would already have been replaced irreversibly.
  return OperatorUtf16Le(name);
}
inline std::string DecodeServingOperator(const Bytes &field) {
  if(field.size()<5||field[4]>field.size()-5)return {};
  return DecodeOperatorText(Bytes(field.begin()+5,field.begin()+5+field[4]));
}
struct OperatorNetwork {
  std::string mcc,mnc;
  uint8_t radio=0;
  bool valid() const {return mcc.size()==3&&(mnc.size()==2||mnc.size()==3);}
  std::string key() const {return valid()?mcc+"-"+mnc:std::string();}
};
inline std::string OperatorDigits(const Bytes &bytes,size_t start,size_t length) {
  if(start>bytes.size()||length>bytes.size()-start)return {};
  std::string out;
  for(size_t i=0;i<length;++i) {
    const auto c=bytes[start+i];
    if(c<'0'||c>'9')return {};
    out.push_back(static_cast<char>(c));
  }
  return out;
}
inline OperatorNetwork CurrentOperatorNetwork(const Values &info) {
  struct Radio {uint8_t service,system,interface;};
  for(bool packet:{true,false}) {
    for(const auto &radio:{Radio{0x4a,0x4b,12},Radio{0x14,0x19,8},
        Radio{0x13,0x18,5},Radio{0x12,0x17,4},Radio{0x24,0x25,9}}) {
      const auto &service=Field(info,radio.service),&field=Field(info,radio.system);
      if(service.size()<3||(service[0]!=1&&service[0]!=2))continue;
      if(packet&&!PacketService(info,radio.service,radio.system))continue;
      // A valid camped PLMN also identifies a network while PS is pending.
      // This lookup does not change registration or authorize a data call.
      if(field.size()<26||field[19]!=1||(field[6]==1&&field[7]!=0))continue;
      OperatorNetwork out;
      out.mcc=OperatorDigits(field,20,3);
      out.mnc=OperatorDigits(field,23,field[25]==0xff||field[25]==0?2:3);
      out.radio=radio.interface;
      if(out.valid()&&out.mcc!="000")return out;
    }
  }
  return {};
}
inline OperatorNetwork ServingOperatorNetwork(const Values &serving) {
  const auto &field=Field(serving,0x12);
  if(field.size()<5)return {};
  const auto mcc=U16(field.data()),mnc=U16(field.data()+2);
  if(mcc==0||mcc>999||mnc>999)return {};
  const auto &pcs=Field(serving,0x27);
  const bool three=mnc>99||(pcs.size()==5&&U16(pcs.data())==mcc&&
      U16(pcs.data()+2)==mnc&&pcs[4]==1);
  OperatorNetwork out;
  out.mcc=std::to_string(mcc);out.mcc.insert(0,3-out.mcc.size(),'0');
  out.mnc=std::to_string(mnc);out.mnc.insert(0,(three?3:2)-out.mnc.size(),'0');
  return out;
}
inline bool AppendOperatorGsm(std::string &out,unsigned septet,bool *escaped) {
  if(septet>0x7f)return false;
  static constexpr uint16_t alphabet[128]={
      0x40,0xa3,0x24,0xa5,0xe8,0xe9,0xf9,0xec,0xf2,0xc7,0x0a,0xd8,0xf8,0x0d,0xc5,0xe5,
      0x394,0x5f,0x3a6,0x393,0x39b,0x3a9,0x3a0,0x3a8,0x3a3,0x398,0x39e,0x1b,0xc6,0xe6,0xdf,0xc9,
      0x20,0x21,0x22,0x23,0xa4,0x25,0x26,0x27,0x28,0x29,0x2a,0x2b,0x2c,0x2d,0x2e,0x2f,
      0x30,0x31,0x32,0x33,0x34,0x35,0x36,0x37,0x38,0x39,0x3a,0x3b,0x3c,0x3d,0x3e,0x3f,
      0xa1,0x41,0x42,0x43,0x44,0x45,0x46,0x47,0x48,0x49,0x4a,0x4b,0x4c,0x4d,0x4e,0x4f,
      0x50,0x51,0x52,0x53,0x54,0x55,0x56,0x57,0x58,0x59,0x5a,0xc4,0xd6,0xd1,0xdc,0xa7,
      0xbf,0x61,0x62,0x63,0x64,0x65,0x66,0x67,0x68,0x69,0x6a,0x6b,0x6c,0x6d,0x6e,0x6f,
      0x70,0x71,0x72,0x73,0x74,0x75,0x76,0x77,0x78,0x79,0x7a,0xe4,0xf6,0xf1,0xfc,0xe0};
  if(!*escaped&&septet==0x1b){*escaped=true;return true;}
  uint32_t scalar=alphabet[septet];
  if(*escaped) {
    *escaped=false;
    switch(septet) {
      case 0x14:scalar='^';break;case 0x28:scalar='{';break;case 0x29:scalar='}';break;
      case 0x2f:scalar='\\';break;case 0x3c:scalar='[';break;case 0x3d:scalar='~';break;
      case 0x3e:scalar=']';break;case 0x40:scalar='|';break;case 0x65:scalar=0x20ac;break;
      default:return false;
    }
  }
  return AppendOperatorScalar(out,scalar);
}
inline std::string OperatorGsmText(const Bytes &bytes) {
  if(bytes.empty()||bytes.size()>512)return {};
  bool escaped=false;std::string out;
  for(auto value:bytes)if(!AppendOperatorGsm(out,value,&escaped))return {};
  return escaped?std::string():out;
}
inline std::string OperatorGsm7(const Bytes &bytes,unsigned spare) {
  if(bytes.empty()||bytes.size()>512||spare>7||bytes.size()*8<spare)return {};
  const size_t count=(bytes.size()*8-spare)/7;
  bool escaped=false;std::string out;
  for(size_t i=0;i<count;++i) {
    const size_t bit=i*7,index=bit/8;
    unsigned value=bytes[index];
    if(index+1<bytes.size())value|=static_cast<unsigned>(bytes[index+1])<<8;
    if(!AppendOperatorGsm(out,(value>>(bit%8))&0x7f,&escaped))return {};
  }
  return escaped?std::string():out;
}
inline std::string DecodePlmnEncoding(uint8_t encoding,const Bytes &bytes,unsigned spare=0) {
  // Get PLMN Name uses GSM/UCS-2 coding, not CDMA description encodings.
  switch(encoding) {
    case 0:return OperatorGsmText(bytes);
    case 9:return OperatorGsm7(bytes,spare);
    case 1:case 4:return OperatorUtf16Le(bytes);
    default:return {};
  }
}
inline std::string DecodePlmnOperator(const Bytes &field) {
  size_t offset=0;
  auto name=[&](bool extended,std::string *out) {
    const size_t header=extended?4:2;
    if(offset>field.size()||header>field.size()-offset)return false;
    const uint8_t encoding=field[offset++];unsigned spare=0;
    if(extended){++offset;spare=field[offset++];}
    const size_t size=field[offset++];
    if(size>field.size()-offset)return false;
    const Bytes bytes(field.begin()+offset,field.begin()+offset+size);offset+=size;
    *out=DecodePlmnEncoding(encoding,bytes,spare);return true;
  };
  std::string provider,short_name,long_name;
  if(!name(false,&provider)||!name(true,&short_name)||!name(true,&long_name))return {};
  if(!long_name.empty())return long_name;
  return short_name.empty()?provider:short_name;
}
inline std::string DecodeBoundOperator(const Values &reply) {
  const auto direct=DecodeOperatorText(Field(reply,0x13));
  if(!direct.empty())return direct;
  const auto &nitz=Field(reply,0x14);
  if(nitz.size()>=6) {
    const size_t long_size=nitz[4],short_at=5+long_size;
    if(short_at<nitz.size()&&nitz[short_at]<=nitz.size()-short_at-1) {
      const auto decode=[&](const Bytes &bytes,unsigned spare) {
        if(nitz[0]==0)return OperatorGsm7(bytes,spare);
        return nitz[0]==1?OperatorUtf16Le(bytes):std::string();
      };
      auto result=decode(Bytes(nitz.begin()+5,nitz.begin()+short_at),nitz[2]);
      if(result.empty())result=decode(Bytes(nitz.begin()+short_at+1,
          nitz.begin()+short_at+1+nitz[short_at]),nitz[3]);
      if(!result.empty())return result;
    }
  }
  const auto &provider=Field(reply,0x10);
  if(provider.size()<2||provider[1]>provider.size()-2)return {};
  Bytes spn(provider.begin()+2,provider.begin()+2+provider[1]);
  if(!spn.empty()&&(spn[0]==0x81||spn[0]==0x82))return {};
  if(!spn.empty()&&spn[0]==0x80) {
    spn.erase(spn.begin());
    while(spn.size()>=2&&spn[spn.size()-1]==0xff&&spn[spn.size()-2]==0xff)
      spn.resize(spn.size()-2);
    if(spn.size()%2&&spn.back()==0xff)spn.pop_back();
    if(spn.size()%2)return {};
    for(size_t i=0;i<spn.size();i+=2)std::swap(spn[i],spn[i+1]);
    return OperatorUtf16Le(spn);
  }
  while(!spn.empty()&&spn.back()==0xff)spn.pop_back();
  const auto gsm=OperatorGsmText(spn);
  return gsm.empty()?OperatorUtf8(spn):gsm;
}
}
