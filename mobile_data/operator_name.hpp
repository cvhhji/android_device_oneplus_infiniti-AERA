/* SPDX-License-Identifier: Apache-2.0 */
#pragma once
#include "qmi.hpp"

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
inline std::string DecodeServingOperator(const Bytes &field) {
  if(field.size()<5||field[4]>field.size()-5)return {};
  const Bytes name(field.begin()+5,field.begin()+5+field[4]);
  Bytes utf8_name=name;
  while(!utf8_name.empty()&&utf8_name.back()==0)utf8_name.pop_back();
  const auto utf8=OperatorUtf8(utf8_name);
  if(!utf8.empty())return utf8;
  // NAS Serving System declares an ASCII description without an encoding
  // byte. This modem returns UCS-2LE here. Decode before JSON serialization,
  // where invalid UTF-8 would already have been replaced irreversibly.
  return OperatorUtf16Le(name);
}
}
