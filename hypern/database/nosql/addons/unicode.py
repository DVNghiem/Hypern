from mongoengine import StringField


class UnicodeField(StringField):
    def validate(self, value):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            self.error("Value must be valid Unicode")
        return True
